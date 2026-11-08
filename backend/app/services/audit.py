"""Append-only audit log with a hash chain (CLAUDE.md 8.6).

The app only ever inserts. Each entry stores the hash of the previous one, so deleting or editing
an entry breaks the chain and ``verify_chain`` reports where. This makes tampering *detectable*;
someone with direct database access can still rewrite the whole chain (see docs/SECURITY.md).
"""

import hashlib
import json
import threading

from bson import ObjectId
from pymongo import DESCENDING
from pymongo.database import Database

from .. import clock
from ..security.masking import mask_text

_lock = threading.Lock()
GENESIS = "0" * 64


def _canonical(entry: dict) -> str:
    def default(value):
        if isinstance(value, ObjectId):
            return str(value)
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    body = {k: v for k, v in entry.items() if k not in ("_id", "hash")}
    return json.dumps(body, sort_keys=True, default=default, separators=(",", ":"))


def _clean(value):
    """Mask any secret-looking text that reaches the audit log by mistake."""
    if isinstance(value, str):
        return mask_text(value)[:2000]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value[:200]]
    return value


def record(
    db: Database,
    action: str,
    result: str = "ok",
    who=None,
    target: dict | None = None,
    details: dict | None = None,
    request_id: str | None = None,
) -> None:
    who_doc = None
    if who is not None:
        who_doc = {"user_id": who.user_id, "username": who.username}
    with _lock:
        last = db.audit_log.find_one(sort=[("seq", DESCENDING)], projection={"seq": 1, "hash": 1})
        now = clock.now()
        entry = {
            "seq": (last["seq"] + 1) if last else 1,
            # MongoDB stores milliseconds; round first so the hash survives the round trip.
            "at": now.replace(microsecond=now.microsecond // 1000 * 1000),
            "who": who_doc,
            "action": action,
            "target": _clean(target) if target else None,
            "result": result,
            "details": _clean(details) if details else None,
            "request_id": request_id,
            "prev_hash": last["hash"] if last else GENESIS,
        }
        entry["hash"] = hashlib.sha256(_canonical(entry).encode()).hexdigest()
        db.audit_log.insert_one(entry)


def verify_chain(db: Database) -> tuple[bool, int | None]:
    """Return (ok, first_bad_seq)."""
    prev = GENESIS
    expected_seq = 1
    for entry in db.audit_log.find(sort=[("seq", 1)]):
        if entry["seq"] != expected_seq or entry["prev_hash"] != prev:
            return False, entry["seq"]
        if hashlib.sha256(_canonical(entry).encode()).hexdigest() != entry["hash"]:
            return False, entry["seq"]
        prev = entry["hash"]
        expected_seq += 1
    return True, None
