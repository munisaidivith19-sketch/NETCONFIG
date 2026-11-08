"""Server-side sessions (CLAUDE.md 8.2).

The browser only holds a random 256-bit token in an httpOnly, SameSite=Strict cookie. MongoDB stores
the SHA-256 of the token, so a database copy cannot be turned back into a working cookie.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from bson import ObjectId
from pymongo.database import Database

from .. import clock
from ..config import Settings

LAST_SEEN_WRITE_EVERY = timedelta(seconds=30)


@dataclass(frozen=True)
class SessionUser:
    session_id: str
    user_id: ObjectId
    username: str
    role: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def create(db: Database, settings: Settings, user: dict, ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    now = clock.now()
    db.sessions.insert_one({
        "_id": _hash(token),
        "user_id": user["_id"],
        "created_at": now,
        "last_seen": now,
        "expires_at": now + timedelta(hours=settings.session_absolute_hours),
        "ip": ip[:64],
        "ua": user_agent[:200],
    })
    return token


def resolve(db: Database, settings: Settings, token: str | None) -> SessionUser | None:
    if not token or len(token) > 100:
        return None
    sid = _hash(token)
    session = db.sessions.find_one({"_id": sid})
    if not session:
        return None
    now = clock.now()
    idle_limit = timedelta(minutes=settings.session_idle_minutes)
    if now >= session["expires_at"] or now - session["last_seen"] > idle_limit:
        db.sessions.delete_one({"_id": sid})
        return None
    user = db.users.find_one({"_id": session["user_id"]}, {"username": 1, "role": 1, "disabled": 1})
    if not user or user.get("disabled"):
        db.sessions.delete_one({"_id": sid})
        return None
    if now - session["last_seen"] > LAST_SEEN_WRITE_EVERY:
        db.sessions.update_one({"_id": sid}, {"$set": {"last_seen": now}})
    return SessionUser(session_id=sid, user_id=user["_id"], username=user["username"], role=user["role"])


def revoke(db: Database, session_id: str) -> None:
    db.sessions.delete_one({"_id": session_id})


def revoke_all_for_user(db: Database, user_id: ObjectId, except_session: str | None = None) -> int:
    query: dict = {"user_id": user_id}
    if except_session:
        query["_id"] = {"$ne": except_session}
    return db.sessions.delete_many(query).deleted_count
