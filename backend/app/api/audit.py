from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from pymongo.database import Database

from ..security.rbac import require_admin
from ..security.sessions import SessionUser
from ..services.audit import verify_chain
from .deps import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntry(BaseModel):
    seq: int
    at: datetime
    username: str | None
    action: str
    target: dict | None
    result: str
    details: dict | None
    request_id: str | None


@router.get("")
def list_audit(
    _: SessionUser = Depends(require_admin),
    db: Database = Depends(get_db),
    action: str | None = Query(None, max_length=64, pattern=r"^[a-z_.]+$"),
    user: str | None = Query(None, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$"),
    result: str | None = Query(None, pattern=r"^(ok|denied|failed)$"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    page: int = Query(1, ge=1, le=10_000),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    # The query is built only from validated scalar values, never from raw client JSON.
    query: dict = {}
    if action:
        query["action"] = {"$regex": "^" + action.replace(".", r"\.")}
    if user:
        query["who.username"] = user
    if result:
        query["result"] = result
    if date_from or date_to:
        query["at"] = {}
        if date_from:
            query["at"]["$gte"] = date_from
        if date_to:
            query["at"]["$lte"] = date_to
    total = db.audit_log.count_documents(query)
    cursor = db.audit_log.find(query, sort=[("seq", -1)]).skip((page - 1) * page_size).limit(page_size)
    items = [
        AuditEntry(
            seq=e["seq"], at=e["at"], username=(e.get("who") or {}).get("username"), action=e["action"],
            target={k: str(v) for k, v in (e.get("target") or {}).items()} or None, result=e["result"],
            details=e.get("details"), request_id=e.get("request_id"),
        )
        for e in cursor
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/verify")
def verify(_: SessionUser = Depends(require_admin), db: Database = Depends(get_db)) -> dict:
    ok, bad = verify_chain(db)
    return {"ok": ok, "first_bad_seq": bad}
