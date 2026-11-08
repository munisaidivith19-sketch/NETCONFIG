from fastapi import APIRouter, Depends, Request
from pymongo.database import Database

from .. import clock
from ..config import Settings
from ..errors import ApiError
from ..models.common import oid
from ..models.user import UserCreate, UserOut, UserUpdate, user_out
from ..security import sessions
from ..security.rbac import require_admin
from ..security.sessions import SessionUser
from ..services import audit
from ..services.users import active_admin_count, create_user, set_password
from .deps import get_db, get_settings, rid

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(_: SessionUser = Depends(require_admin), db: Database = Depends(get_db)) -> list[UserOut]:
    now = clock.now()
    return [user_out(u, now) for u in db.users.find({}, sort=[("username", 1)]).limit(500)]


@router.post("", status_code=201)
def add_user(body: UserCreate, request: Request, admin: SessionUser = Depends(require_admin),
             db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserOut:
    doc = create_user(db, settings, body.username, body.password, body.role)
    audit.record(db, "user.create", who=admin, target={"type": "user", "id": str(doc["_id"])},
                 details={"username": body.username, "role": body.role}, request_id=rid(request))
    return user_out(doc, clock.now())


def _would_remove_last_admin(db: Database, target: dict) -> bool:
    return target["role"] == "admin" and not target.get("disabled") and active_admin_count(db) <= 1


@router.patch("/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, admin: SessionUser = Depends(require_admin),
                db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserOut:
    target = db.users.find_one({"_id": oid(user_id)})
    if target is None:
        raise ApiError(404, "User not found.")

    demoting = body.role is not None and body.role != "admin"
    disabling = body.disabled is True
    if (demoting or disabling) and _would_remove_last_admin(db, target):
        raise ApiError(409, "You cannot demote or disable the last active admin.")

    changes: dict = {}
    if body.role is not None:
        changes["role"] = body.role
    if body.disabled is not None:
        changes["disabled"] = body.disabled
    if body.unlock:
        changes.update({"locked_until": None, "failed_logins": 0})
    if changes:
        changes["updated_at"] = clock.now()
        db.users.update_one({"_id": target["_id"]}, {"$set": changes})
    if body.new_password is not None:
        set_password(db, settings, target, body.new_password)
    if body.disabled or body.new_password is not None or body.role is not None:
        sessions.revoke_all_for_user(db, target["_id"])

    audit.record(db, "user.update", who=admin, target={"type": "user", "id": user_id},
                 details={"fields": sorted(k for k, v in body.model_dump().items()
                                           if v is not None and k != "new_password")
                          + (["password_reset"] if body.new_password else [])},
                 request_id=rid(request))
    return user_out(db.users.find_one({"_id": target["_id"]}), clock.now())


@router.delete("/{user_id}")
def delete_user(user_id: str, request: Request, admin: SessionUser = Depends(require_admin),
                db: Database = Depends(get_db)) -> dict:
    target = db.users.find_one({"_id": oid(user_id)})
    if target is None:
        raise ApiError(404, "User not found.")
    if target["_id"] == admin.user_id:
        raise ApiError(409, "You cannot delete your own account.")
    if _would_remove_last_admin(db, target):
        raise ApiError(409, "You cannot delete the last active admin.")
    db.users.delete_one({"_id": target["_id"]})
    sessions.revoke_all_for_user(db, target["_id"])
    audit.record(db, "user.delete", who=admin, target={"type": "user", "id": user_id},
                 details={"username": target["username"]}, request_id=rid(request))
    return {"ok": True}
