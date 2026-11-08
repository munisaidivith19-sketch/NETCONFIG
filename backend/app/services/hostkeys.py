"""SSH host-key pinning (CLAUDE.md 8.5): trust on first use, then refuse any other key until an admin
accepts it. This protects device passwords and configuration against a man-in-the-middle."""

from collections.abc import Callable

from pymongo import ReturnDocument
from pymongo.database import Database

from .. import clock
from ..models.device import is_lab_address
from . import audit
from .connection import ConnectFailed, Connection, ConnectParams, HostKey, open_netmiko, probe_host_key


def _key_doc(key: HostKey) -> dict:
    return {"key_type": key.key_type, "key_b64": key.key_b64, "fingerprint": key.fingerprint}


def verify(db: Database, host: str, port: int, observed: HostKey, who=None) -> tuple[str, dict]:
    """Return ("new" | "trusted", doc), or raise ConnectFailed when the key changed."""
    now = clock.now()
    doc = db.host_keys.find_one({"host": host, "port": port})
    if doc is None:
        doc = {"host": host, "port": port, **_key_doc(observed), "first_seen": now, "last_seen": now,
               "pending": None, "accepted_by": None}
        doc["_id"] = db.host_keys.insert_one(doc).inserted_id
        audit.record(db, "hostkey.first_seen", who=who, target={"type": "host", "id": f"{host}:{port}"},
                     details={"fingerprint": observed.fingerprint, "key_type": observed.key_type})
        return "new", doc
    if doc["key_type"] == observed.key_type and doc["key_b64"] == observed.key_b64:
        db.host_keys.update_one({"_id": doc["_id"]}, {"$set": {"last_seen": now}})
        return "trusted", doc
    db.host_keys.update_one({"_id": doc["_id"]}, {"$set": {"pending": {**_key_doc(observed), "seen_at": now}}})
    audit.record(db, "hostkey.changed", result="denied", who=who, target={"type": "host", "id": f"{host}:{port}"},
                 details={"pinned": doc["fingerprint"], "offered": observed.fingerprint})
    raise ConnectFailed("hostkey", f"SSH host key of {host}:{port} CHANGED (pinned {doc['fingerprint']}, offered "
                                   f"{observed.fingerprint}). Refused: an admin must accept the new key first.")


def accept(db: Database, key_id, who) -> dict | None:
    doc = db.host_keys.find_one({"_id": key_id})
    if not doc or not doc.get("pending"):
        return None
    pending = doc["pending"]
    new = db.host_keys.find_one_and_update(
        {"_id": key_id, "pending.key_b64": pending["key_b64"]},
        {"$set": {"key_type": pending["key_type"], "key_b64": pending["key_b64"], "fingerprint": pending["fingerprint"],
                  "pending": None, "accepted_by": who.username, "accepted_at": clock.now()}},
        return_document=ReturnDocument.AFTER)
    audit.record(db, "hostkey.accept", who=who, target={"type": "host", "id": f"{doc['host']}:{doc['port']}"},
                 details={"old": doc["fingerprint"], "new": pending["fingerprint"]})
    return new


class Connector:
    """Opens a Connection for one device, enforcing the connection rules before anything is sent."""

    def __init__(self, db: Database, probe: Callable[[str, int], HostKey] = probe_host_key,
                 opener: Callable[[ConnectParams], Connection] = open_netmiko):
        self.db = db
        self.probe = probe
        self.opener = opener

    def open(self, params: ConnectParams, who=None, notes: list[str] | None = None) -> Connection:
        notes = notes if notes is not None else []
        if params.method == "telnet_lab":
            if not params.host or not is_lab_address(params.host):
                raise ConnectFailed("telnet", "Telnet is allowed only to loopback or private (RFC 1918) lab addresses.")
            notes.append("INSECURE: lab console over Telnet – the password is sent in clear text.")
        if params.method == "ssh":
            observed = self.probe(params.host, params.port)
            state, doc = verify(self.db, params.host, params.port, observed, who)
            if state == "new":
                notes.append(f"First connection: host key {observed.fingerprint} ({observed.key_type}) stored.")
            params.pinned_key = observed
        return self.opener(params)
