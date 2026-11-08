"""User accounts: creation, login checks and lockout."""

from datetime import timedelta

from pymongo.collation import Collation
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import clock
from ..config import Settings
from ..errors import ApiError
from ..security.passwords import hash_password, policy_errors, verify_password

CI = Collation(locale="en", strength=2)


def find_by_username(db: Database, username: str) -> dict | None:
    return db.users.find_one({"username": username}, collation=CI)


def create_user(db: Database, settings: Settings, username: str, password: str, role: str) -> dict:
    problems = policy_errors(password, username)
    if problems:
        raise ApiError(422, "Password does not meet the policy.", fields={"password": " ".join(problems)})
    now = clock.now()
    doc = {
        "username": username,
        "password_hash": hash_password(password, settings.bcrypt_rounds),
        "role": role,
        "disabled": False,
        "failed_logins": 0,
        "locked_until": None,
        "password_changed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    try:
        doc["_id"] = db.users.insert_one(doc).inserted_id
    except DuplicateKeyError as exc:
        raise ApiError(409, "That username is already taken.", fields={"username": "already taken"}) from exc
    return doc


def authenticate(db: Database, settings: Settings, username: str, password: str) -> tuple[dict | None, str]:
    """Return (user, reason). reason is one of ok, unknown, bad_password, locked, disabled.

    The HTTP layer shows one generic message for every failure, so nobody can tell
    which usernames exist.
    """
    user = find_by_username(db, username)
    if user is None:
        verify_password(password, None)  # same bcrypt cost as a real check
        return None, "unknown"

    now = clock.now()
    locked_until = user.get("locked_until")
    if locked_until and locked_until > now:
        verify_password(password, None)
        return None, "locked"

    if not verify_password(password, user.get("password_hash")):
        failures = user.get("failed_logins", 0) + 1
        update: dict = {"failed_logins": failures}
        if failures >= settings.lockout_threshold:
            update = {"failed_logins": 0, "locked_until": now + timedelta(minutes=settings.lockout_minutes)}
        db.users.update_one({"_id": user["_id"]}, {"$set": update})
        return None, "locked_now" if "locked_until" in update else "bad_password"

    if user.get("disabled"):
        return None, "disabled"

    db.users.update_one({"_id": user["_id"]}, {"$set": {"failed_logins": 0, "locked_until": None,
                                                         "last_login_at": now}})
    return user, "ok"


def set_password(db: Database, settings: Settings, user: dict, new_password: str) -> None:
    problems = policy_errors(new_password, user["username"])
    if problems:
        raise ApiError(422, "Password does not meet the policy.", fields={"new_password": " ".join(problems)})
    now = clock.now()
    db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"password_hash": hash_password(new_password, settings.bcrypt_rounds),
                  "password_changed_at": now, "updated_at": now}},
    )


def active_admin_count(db: Database) -> int:
    return db.users.count_documents({"role": "admin", "disabled": {"$ne": True}})
