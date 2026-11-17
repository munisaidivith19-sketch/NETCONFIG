"""Read-only device discovery (Phase 4B): facts, OS / model detection, LLDP/CDP neighbours and VLANs.

The engineer types a device login once; it is used for this one read and then dropped (CLAUDE.md 8.3). The
connection goes through the same Connector as a push, so the SSH host key is pinned and Telnet is limited to
lab addresses. Only ``show`` commands from the driver are sent – nothing on the device is changed – and only
parsed, length-limited values are stored, never the raw output.
"""

import re
from dataclasses import dataclass

from pydantic import SecretStr
from pymongo.database import Database

from .. import clock
from ..drivers.base import ModelInfo
from ..drivers.registry import get_driver
from .connection import ConnectFailed, ConnectionLost, ConnectParams, default_port

# Text that identifies an OS in "show version" (or the OS's equivalent). Used to warn when the device is not
# running the OS of the catalog model the engineer chose.
OS_SIGNATURES = [
    ("cisco_ios", r"Cisco IOS|IOS-XE|IOS XE"),
    ("arista_eos", r"\bArista\b"),
    ("juniper_junos", r"^\s*Junos:|\bJUNOS\b"),
    ("aruba_aoscx", r"ArubaOS-CX|AOS-CX"),
    ("mikrotik_routeros", r"RouterOS|MikroTik"),
    ("huawei_vrp", r"Huawei Versatile Routing Platform|VRP \(R\) software"),
    ("dlink_ds", r"D-Link|\bDGS-\d"),
    ("tplink_jetstream", r"TP-Link|JetStream"),
]
FACT_KEYS = ("model", "version", "serial", "hostname")
MAX_NEIGHBORS = 256
MAX_VLANS = 4094
CONNECT_METHODS = ("ssh", "telnet_lab")


class DiscoveryError(Exception):
    """A safe message for the browser (no secrets, no raw device output). ``status``: 422 for a device that
    cannot be read this way, 502 when the device itself failed."""

    def __init__(self, message: str, status: int = 502):
        self.status = status
        super().__init__(message)


@dataclass
class Login:
    username: str
    password: SecretStr
    secret: SecretStr | None = None


def clean(value, limit: int = 80) -> str | None:
    """Device output is untrusted: keep printable ASCII only and cap the length before storing it."""
    if value is None:
        return None
    text = re.sub(r"[^\x20-\x7e]", "", str(value)).strip()
    return text[:limit] or None


def detect_os(outputs: dict[str, str]) -> str | None:
    text = "\n".join(outputs.values())
    return next((os_id for os_id, pattern in OS_SIGNATURES if re.search(pattern, text, re.M)), None)


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def model_match(model_doc: dict, os_id: str, detected_os: str | None, detected_model: str | None) -> dict:
    """Compare what the device reports with the catalog model the engineer chose."""
    expected = model_doc.get("name", model_doc["_id"])
    if detected_os and detected_os != os_id:
        return {"status": "mismatch", "detected_os": detected_os, "detected_model": detected_model,
                "expected_model": expected,
                "message": f"The device looks like {detected_os}, but its catalog model uses {os_id}. "
                           "Check the model before pushing: the commands would be wrong."}
    if not detected_model:
        return {"status": "unknown", "detected_os": detected_os, "detected_model": None, "expected_model": expected,
                "message": "The model could not be read from the device output."}
    got = _norm(detected_model)
    names = [_norm(expected), _norm(model_doc["_id"]), *(_norm(p) for p in re.findall(r"\(([^)]+)\)", expected))]
    ok = any(got and n and (got in n or n in got) for n in names)
    return {"status": "match" if ok else "mismatch", "detected_os": detected_os, "detected_model": detected_model,
            "expected_model": expected,
            "message": "" if ok else f"The device reports model {detected_model}, but the inventory says {expected}."}


def _neighbor(n: dict) -> dict:
    return {"local": clean(n.get("local"), 48), "remote": clean(n.get("remote"), 64), "port": clean(n.get("port"), 48),
            "ip": clean(n.get("ip"), 45), "protocol": clean(n.get("protocol"), 8)}


def discover(db: Database, connector, settings, device: dict, login: Login, who=None) -> dict:
    """Connect, run the driver's read-only commands and return the fields to store on the device."""
    conn_cfg = device.get("connection", {})
    method = conn_cfg.get("method")
    if method not in CONNECT_METHODS or not device.get("mgmt_ip"):
        raise DiscoveryError("Device facts are read over SSH (or a lab console): the device needs a management "
                             "address and an SSH or lab-console connection.", 422)
    model_doc = db.catalog_models.find_one({"_id": device["model_id"]})
    if not model_doc:
        raise DiscoveryError("The device's catalog model no longer exists.", 422)
    driver = get_driver(device["os_id"], ModelInfo.from_doc(model_doc), settings)
    if driver is None:
        raise DiscoveryError("This device has no enabled driver, so its facts cannot be read.", 422)
    port = conn_cfg.get("port") or default_port(method)
    params = ConnectParams(method=method, device_type=driver.netmiko_device_type, host=device["mgmt_ip"], port=port,
                           username=login.username, password=login.password, secret=login.secret,
                           config_prompt=driver.config_prompt)
    commands = [*driver.facts_commands(), *driver.vlan_commands(), *driver.neighbor_commands()]
    outputs: dict[str, str] = {}
    notes: list[str] = []
    try:
        conn = connector.open(params, who=who, notes=notes)
    except ConnectFailed as exc:
        raise DiscoveryError(exc.message) from exc
    try:
        for cmd in commands:
            outputs[cmd] = conn.show(cmd)
    except ConnectionLost as exc:
        raise DiscoveryError("The connection to the device broke while reading its facts.") from exc
    finally:
        conn.close()
        params.password = params.secret = None

    parsed = driver.parse_facts(outputs)
    facts = {k: clean(parsed.get(k)) for k in FACT_KEYS}
    detected_os = detect_os({c: outputs[c] for c in driver.facts_commands() if c in outputs})
    now = clock.now()
    facts.update(source="cli", read_at=now, match=model_match(model_doc, device["os_id"], detected_os, facts["model"]))
    neighbors = [_neighbor(n) for n in driver.parse_neighbors(outputs)[:MAX_NEIGHBORS]]
    vlans = [{"id": v["id"], "name": clean(v["name"], 32)} for v in driver.parse_vlans(outputs)[:MAX_VLANS]]
    return {"facts": facts, "neighbors": [n for n in neighbors if n["local"] and n["remote"]],
            "vlans": vlans if driver.vlan_commands() else None, "notes": notes,
            "status": {**device.get("status", {}), "reachable": True, "ssh": True, "checked_at": now}}
