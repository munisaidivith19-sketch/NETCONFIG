from fastapi import APIRouter, Depends, Query, Request
from pymongo.database import Database

from ..errors import ApiError
from ..models.common import oid
from ..security.rbac import require_admin
from ..security.sessions import SessionUser
from ..services import audit, hostkeys
from .deps import get_db, rid

router = APIRouter(prefix="/api/hostkeys", tags=["hostkeys"])


def _out(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in ("_id", "key_b64")}
    out["id"] = str(doc["_id"])
    if out.get("pending"):
        out["pending"] = {k: v for k, v in out["pending"].items() if k != "key_b64"}
    return out


@router.get("")
def list_keys(_: SessionUser = Depends(require_admin), db: Database = Depends(get_db),
              pending: bool = Query(False)) -> list[dict]:
    query = {"pending": {"$ne": None}} if pending else {}
    return [_out(d) for d in db.host_keys.find(query, sort=[("host", 1), ("port", 1)]).limit(500)]


@router.post("/{key_id}/accept")
def accept_key(key_id: str, request: Request, user: SessionUser = Depends(require_admin),
               db: Database = Depends(get_db)) -> dict:
    """Trust the new key a device offered. Do this only after checking the fingerprint on the device."""
    new = hostkeys.accept(db, oid(key_id), user)
    if new is None:
        raise ApiError(409, "This host has no pending key change.")
    return _out(new)


@router.delete("/{key_id}", status_code=204)
def forget_key(key_id: str, request: Request, user: SessionUser = Depends(require_admin),
               db: Database = Depends(get_db)) -> None:
    doc = db.host_keys.find_one_and_delete({"_id": oid(key_id)})
    if not doc:
        raise ApiError(404, "Host key not found.")
    audit.record(db, "hostkey.forget", who=user, target={"type": "host", "id": f"{doc['host']}:{doc['port']}"},
                 details={"fingerprint": doc["fingerprint"]}, request_id=rid(request))
