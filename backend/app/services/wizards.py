"""JobCreate → one prepared step per device (docs/SYSTEM_DESIGN.md 5.7). Used by POST /jobs/preview and
POST /jobs, so the preview and the job can never disagree.

The wizards never write device commands themselves: they only build ordinary ConfigPlans, and
planning.prepare() validates and generates them exactly like a single-device plan.
"""

import ipaddress
from dataclasses import dataclass, field

from pymongo.database import Database

from ..config import Settings
from ..errors import ApiError
from ..models.common import oid
from ..models.job import JobCreate
from ..models.plan import ConfigPlan
from ..models.wizards import BootstrapSpec, LinkEnd, LinkSpec
from . import planning
from .planning import Prepared

CONSOLE_METHODS = ("serial", "telnet_lab")
ROUTING_CATEGORIES = ("router", "l3switch")
SWITCH_CATEGORIES = ("switch", "l3switch")
# Settings that belong to one device only: pushing them to many switches would create duplicates.
PER_DEVICE = {"basic": "hostname", "ssh": "SSH user", "svis": "VLAN interface IPs", "interfaces": "interface IPs",
              "dhcp": "DHCP pools", "nat": "NAT", "statics": "static routes", "default_gateway": "default gateway",
              "routing": "routing"}


@dataclass
class BuiltStep:
    prepared: Prepared
    role: str | None = None  # link: "A" / "B"


@dataclass
class Built:
    kind: str
    steps: list[BuiltStep] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)  # link: do both sides match?
    bootstrap: dict | None = None  # {"mgmt_ip": new address, "admin_username": ...}

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.steps) and all(s.prepared.ok for s in self.steps)

    @property
    def production(self) -> bool:
        return any(s.prepared.production for s in self.steps)


def build(db: Database, settings: Settings, body: JobCreate) -> Built:
    return {"push": _push, "multi": _multi, "link": _link, "bootstrap": _bootstrap}[body.kind](db, settings, body)


# ----------------------------------------------------------------------- push / multi
def _push(db, settings, body: JobCreate) -> Built:
    p = planning.prepare(db, settings, body.plan, device_id=body.device_id)
    return Built("push", [BuiltStep(p)], dict(p.errors), list(p.warnings))


def _multi(db, settings, body: JobCreate) -> Built:
    b = Built("multi")
    plan = body.plan
    for name, what in PER_DEVICE.items():
        value = getattr(plan, name)
        if value:
            b.errors[f"plan.{name}"] = f"{what} is set per device; configure it on one device at a time"
    if b.errors:
        return b
    for i, device_id in enumerate(body.device_ids):
        p = planning.prepare(db, settings, plan, device_id=device_id)
        b.steps.append(BuiltStep(p))
        if p.model.get("category") not in SWITCH_CATEGORIES:
            p.errors.setdefault("device_id", f"{p.device['name']} is not a switch")
        for path, msg in p.errors.items():
            b.errors[f"steps.{i}.{path}"] = f"{p.device['name']}: {msg}"
        b.warnings += [f"{p.device['name']}: {w}" for w in p.warnings]
    b.warnings.append("Switches are changed one after another"
                      + (", stopping at the first one that fails." if body.stop_on_failure else "."))
    return b


# ------------------------------------------------------------------------------ link
def _device(db: Database, device_id: str) -> dict | None:
    return db.devices.find_one({"_id": oid(device_id)})


def link_addresses(subnet: str) -> tuple[str, str, int]:
    """A /30 gives its two host addresses; a /31 (RFC 3021) uses both of its addresses."""
    net = ipaddress.IPv4Network(subnet)
    if net.prefixlen == 31:
        return str(net.network_address), str(net.broadcast_address), 31
    hosts = list(net.hosts())
    return str(hosts[0]), str(hosts[1]), net.prefixlen


def _link_spec_errors(spec: LinkSpec, dev_a: dict | None, dev_b: dict | None, models: dict) -> dict[str, str]:
    e: dict[str, str] = {}
    for side, dev in (("a", dev_a), ("b", dev_b)):
        if dev is None:
            e[f"link.{side}.device_id"] = "device not found"
        elif models.get(side, {}).get("category") not in ROUTING_CATEGORIES:
            e[f"link.{side}.device_id"] = f"{dev['name']} is not a router or Layer 3 switch"
    if spec.a.device_id == spec.b.device_id:
        e["link.b.device_id"] = "pick two different devices"
    try:
        net = ipaddress.IPv4Network(spec.subnet, strict=True)
        if net.prefixlen not in (30, 31):
            e["link.subnet"] = "use a /30 or /31 for a point-to-point link"
    except ValueError:
        try:
            e["link.subnet"] = f"host bits are set; did you mean {ipaddress.IPv4Network(spec.subnet, strict=False)}?"
        except ValueError:
            e["link.subnet"] = "not a valid network (example 10.255.0.0/30)"
    label = {"ospf": "OSPF", "eigrp": "EIGRP", "bgp": "BGP"}.get(spec.protocol)
    if label:
        for side in ("a", "b"):
            if not getattr(spec, side).router_id:
                e[f"link.{side}.router_id"] = f"required for {label}"
        if spec.a.router_id and spec.a.router_id == spec.b.router_id:
            e["link.b.router_id"] = "the two routers need different router IDs"
    if spec.protocol == "eigrp" and spec.eigrp_asn is None:
        e["link.eigrp_asn"] = "required for EIGRP (the same AS on both sides)"
    if spec.protocol == "bgp":
        for side in ("a", "b"):
            if getattr(spec, side).asn is None:
                e[f"link.{side}.asn"] = "required for BGP"
        if spec.a.asn and spec.a.asn == spec.b.asn:
            e["link.b.asn"] = "use a different AS than the other side (only eBGP is supported)"
    return e


def _side_plan(spec: LinkSpec, me: LinkEnd, other: LinkEnd, my_ip: str, other_ip: str, plen: int,
               other_name: str) -> ConfigPlan:
    desc = (spec.description or f"link to {other_name}")[:80]
    plan: dict = {"interfaces": [{"interface": me.interface, "ip": f"{my_ip}/{plen}", "description": desc}],
                  "revert_minutes": spec.revert_minutes}
    if spec.protocol == "ospf":
        plan["routing"] = {"ospf": {"process_id": spec.ospf_process_id, "router_id": me.router_id,
                                    "interfaces": [{"interface": me.interface, "area": spec.ospf_area}]}}
    elif spec.protocol == "eigrp":
        plan["routing"] = {"eigrp": {"asn": spec.eigrp_asn, "router_id": me.router_id,
                                     "networks": [str(ipaddress.IPv4Network(spec.subnet))]}}
    elif spec.protocol == "bgp":
        plan["routing"] = {"bgp": {"asn": me.asn, "router_id": me.router_id,
                                   "neighbors": [{"ip": other_ip, "remote_as": other.asn, "description": desc}]}}
    return ConfigPlan.model_validate(plan)


def link_match(a: ConfigPlan, b: ConfigPlan, names: tuple[str, str]) -> list[dict]:
    """Read the two finished plans back and check that they describe the same link."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    ia, ib = ipaddress.IPv4Interface(a.interfaces[0].ip), ipaddress.IPv4Interface(b.interfaces[0].ip)
    add(f"Same subnet {ia.network}", ia.network == ib.network, f"{names[0]} {ia.ip} – {names[1]} {ib.ip}")
    add("Different addresses", ia.ip != ib.ip)
    ra, rb = a.routing, b.routing
    if ra and ra.ospf and rb and rb.ospf:
        area_a, area_b = ra.ospf.interfaces[0].area, rb.ospf.interfaces[0].area
        add(f"Same OSPF area ({area_a})", area_a == area_b)
        add("Different OSPF router IDs", ra.ospf.router_id != rb.ospf.router_id,
            f"{ra.ospf.router_id} / {rb.ospf.router_id}")
    if ra and ra.eigrp and rb and rb.eigrp:
        add(f"Same EIGRP AS ({ra.eigrp.asn})", ra.eigrp.asn == rb.eigrp.asn)
        add("Both advertise the link subnet", str(ia.network) in ra.eigrp.networks and
            str(ib.network) in rb.eigrp.networks)
    if ra and ra.bgp and rb and rb.bgp:
        na, nb = ra.bgp.neighbors[0], rb.bgp.neighbors[0]
        add(f"{names[0]} peers with {ib.ip} in AS {rb.bgp.asn}",
            na.ip == str(ib.ip) and na.remote_as == rb.bgp.asn, f"neighbor {na.ip} remote-as {na.remote_as}")
        add(f"{names[1]} peers with {ia.ip} in AS {ra.bgp.asn}",
            nb.ip == str(ia.ip) and nb.remote_as == ra.bgp.asn, f"neighbor {nb.ip} remote-as {nb.remote_as}")
    if bool(ra) != bool(rb):
        add("Same routing protocol on both sides", False)
    return checks


_LINK_PATHS = [("device_id", "device_id"), ("interfaces.0.interface", "interface"), ("interfaces", "device_id"),
               ("routing.ospf.interfaces", "interface"), ("routing.ospf.router_id", "router_id"),
               ("routing.eigrp.router_id", "router_id"), ("routing.bgp.router_id", "router_id"),
               ("routing.bgp", "asn"), ("commands", "interface")]


def _link_path(side: str, path: str) -> str:
    if path.startswith("interfaces.0.ip"):
        return "link.subnet"
    if path in ("routing.ospf", "routing.eigrp", "routing.bgp"):
        return "link.protocol"
    for prefix, name in _LINK_PATHS:
        if path == prefix or path.startswith(prefix + "."):
            return f"link.{side}.{name}"
    return f"link.{side}.{path}"


def _link(db, settings, body: JobCreate) -> Built:
    spec = body.link
    b = Built("link")
    dev_a, dev_b = _device(db, spec.a.device_id), _device(db, spec.b.device_id)
    models = {side: db.catalog_models.find_one({"_id": d["model_id"]}) or {}
              for side, d in (("a", dev_a), ("b", dev_b)) if d}
    b.errors = _link_spec_errors(spec, dev_a, dev_b, models)
    if b.errors:
        return b
    ip_a, ip_b, plen = link_addresses(spec.subnet)
    plans = {"a": _side_plan(spec, spec.a, spec.b, ip_a, ip_b, plen, dev_b["name"]),
             "b": _side_plan(spec, spec.b, spec.a, ip_b, ip_a, plen, dev_a["name"])}
    for side, dev in (("a", dev_a), ("b", dev_b)):
        p = planning.prepare(db, settings, plans[side], device_id=str(dev["_id"]))
        b.steps.append(BuiltStep(p, role=side.upper()))
        for path, msg in p.errors.items():
            b.errors.setdefault(_link_path(side, path), f"{dev['name']}: {msg}")
        b.warnings += [f"{dev['name']}: {w}" for w in p.warnings]
    b.checks = link_match(b.steps[0].prepared.plan, b.steps[1].prepared.plan, (dev_a["name"], dev_b["name"]))
    for c in b.checks:
        if not c["ok"]:
            b.errors.setdefault("link", f"The two sides do not match: {c['name']}")
    b.warnings.append(f"Both sides are applied and verified first, then confirmed together. If either side fails, "
                      f"both are rolled back. Routing neighbours can take a minute to come up after "
                      f"{dev_b['name']} is configured.")
    return b


# ------------------------------------------------------------------------- bootstrap
_BOOT_PATHS = {"basic.hostname": "hostname", "basic.domain": "domain", "basic": "hostname",
               "ssh.username": "admin_username", "ssh": "admin_username", "svis.0.ip": "mgmt.ip",
               "interfaces.0.ip": "mgmt.ip", "svis.0.vlan": "mgmt.vlan", "vlans.0.id": "mgmt.vlan",
               "interfaces.0.interface": "mgmt.interface", "default_gateway": "mgmt.gateway",
               "statics.0.next_hop": "mgmt.gateway", "svis": "mgmt.vlan", "interfaces": "mgmt.interface",
               "commands": "mgmt.ip"}


def bootstrap_plan(spec: BootstrapSpec, category: str) -> tuple[ConfigPlan | None, dict[str, str]]:
    e: dict[str, str] = {}
    try:
        iface = ipaddress.IPv4Interface(spec.mgmt.ip)
    except ValueError:
        return None, {"bootstrap.mgmt.ip": "not a valid address/prefix (example 10.0.0.2/24)"}
    if spec.mgmt.gateway:
        try:
            gw = ipaddress.IPv4Address(spec.mgmt.gateway)
        except ValueError:  # the pattern lets 300.1.1.1 through; ipaddress decides
            return None, {"bootstrap.mgmt.gateway": "not a valid IPv4 address"}
        net = iface.network
        if gw not in net or gw in (net.network_address, net.broadcast_address):
            e["bootstrap.mgmt.gateway"] = f"the gateway must be a host address inside {net}"
        elif gw == iface.ip:
            e["bootstrap.mgmt.gateway"] = "the gateway cannot be the device's own address"
    plan: dict = {
        "basic": {"hostname": spec.hostname, "domain": spec.domain},
        "ssh": {"username": spec.admin_username, "set_enable_secret": True, "rsa_modulus": spec.rsa_modulus,  # nosec B105
                "vty_timeout_minutes": spec.vty_timeout_minutes},
        "revert_minutes": spec.revert_minutes, "save": True,
    }
    if spec.hardening:
        plan["hardening"] = {}
    if category in SWITCH_CATEGORIES:
        if spec.mgmt.interface:
            e["bootstrap.mgmt.interface"] = "switches are managed through a VLAN interface: set mgmt.vlan instead"
        plan["svis"] = [{"vlan": spec.mgmt.vlan, "ip": spec.mgmt.ip, "description": "management"}]
        if spec.mgmt.vlan != 1:
            plan["vlans"] = [{"id": spec.mgmt.vlan, "name": "MGMT"}]
    elif category == "router":
        if not spec.mgmt.interface:
            e["bootstrap.mgmt.interface"] = "choose the router port that connects to the management network"
        else:
            plan["interfaces"] = [{"interface": spec.mgmt.interface, "ip": spec.mgmt.ip, "description": "management"}]
    else:
        e["device_id"] = "first-time setup is available for switches and routers"
    if spec.mgmt.gateway:
        if category == "switch":
            plan["default_gateway"] = spec.mgmt.gateway
        else:
            plan["statics"] = [{"prefix": "0.0.0.0/0", "next_hop": spec.mgmt.gateway}]  # noqa: S104 - a route
    if e:
        return None, e
    return ConfigPlan.model_validate(plan), {}


def _bootstrap(db, settings, body: JobCreate) -> Built:
    spec = body.bootstrap
    b = Built("bootstrap")
    device = _device(db, body.device_id)
    if not device:
        raise ApiError(404, "Device not found.")
    method = device.get("connection", {}).get("method")
    if method not in CONSOLE_METHODS:
        b.errors["device_id"] = ("first-time setup runs over the serial console or a lab console; this device "
                                 f"uses {method}. Change its connection method first.")
        return b
    model = db.catalog_models.find_one({"_id": device["model_id"]}) or {}
    plan, errors = bootstrap_plan(spec, model.get("category", ""))
    new_ip = str(ipaddress.IPv4Interface(spec.mgmt.ip).ip) if "bootstrap.mgmt.ip" not in errors else None
    if new_ip:
        other = db.devices.find_one({"mgmt_ip": new_ip, "_id": {"$ne": device["_id"]}}, {"name": 1})
        if other:
            errors["bootstrap.mgmt.ip"] = f"{new_ip} is already used by {other['name']}"
    b.errors.update(errors)
    if plan is None or b.errors:
        return b
    p = planning.prepare(db, settings, plan, device_id=body.device_id)
    b.steps.append(BuiltStep(p))
    for path, msg in p.errors.items():
        key = next((v for k, v in _BOOT_PATHS.items() if path == k or path.startswith(k + ".")), None)
        b.errors.setdefault(f"bootstrap.{key}" if key else (path if path == "device_id" else f"bootstrap.{path}"), msg)
    b.warnings += p.warnings
    b.warnings.append(f"After the change is saved, NetConfig Studio tries an SSH login to {new_ip} as "
                      f"{spec.admin_username}. Only if it works is the device switched to SSH.")
    b.bootstrap = {"mgmt_ip": new_ip, "admin_username": spec.admin_username}
    return b
