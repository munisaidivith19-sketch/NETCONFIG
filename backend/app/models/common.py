"""Shared Pydantic building blocks. Every request model forbids unknown fields (CLAUDE.md 8.4)."""

from typing import Annotated

from bson import ObjectId
from bson.errors import InvalidId
from pydantic import BaseModel, ConfigDict, StringConstraints

from ..errors import ApiError


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=False)


Username = Annotated[str, StringConstraints(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")]
Password = Annotated[str, StringConstraints(min_length=1, max_length=128, strip_whitespace=False)]
ObjectIdStr = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{24}$")]


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise ApiError(404, "Not found.") from exc


class Page(BaseModel):
    items: list
    total: int
    page: int
    page_size: int
