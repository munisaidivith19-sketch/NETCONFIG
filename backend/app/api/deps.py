from fastapi import Request
from pymongo.database import Database

from ..config import Settings
from ..security.clientip import forwarded_ip


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    settings = request.app.state.settings
    if not settings.demo_mode:
        return peer  # locally nothing sits in front of the app, so X-Forwarded-For is never trusted
    return forwarded_ip(peer, request.headers.getlist("x-forwarded-for"), settings.trusted_proxy_hops)


def rid(request: Request) -> str:
    return getattr(request.state, "request_id", "-")
