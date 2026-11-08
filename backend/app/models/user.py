from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .common import Password, StrictModel, Username

Role = Literal["admin", "engineer", "viewer"]


class LoginRequest(StrictModel):
    username: Username
    password: Password


class PasswordChange(StrictModel):
    current_password: Password
    new_password: Password


class UserCreate(StrictModel):
    username: Username
    password: Password
    role: Role


class UserUpdate(StrictModel):
    role: Role | None = None
    disabled: bool | None = None
    unlock: bool | None = None
    new_password: Password | None = None


class UserOut(BaseModel):
    id: str
    username: str
    role: Role
    disabled: bool = False
    locked: bool = False
    created_at: datetime | None = None


def user_out(doc: dict, now: datetime) -> UserOut:
    locked_until = doc.get("locked_until")
    return UserOut(
        id=str(doc["_id"]),
        username=doc["username"],
        role=doc["role"],
        disabled=bool(doc.get("disabled")),
        locked=bool(locked_until and locked_until > now),
        created_at=doc.get("created_at"),
    )
