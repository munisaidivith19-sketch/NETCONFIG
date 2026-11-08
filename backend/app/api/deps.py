from fastapi import Request
from pymongo.database import Database

from ..config import Settings


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rid(request: Request) -> str:
    return getattr(request.state, "request_id", "-")
