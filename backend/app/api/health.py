from fastapi import APIRouter, Depends, Request
from pymongo.database import Database

from .. import __version__
from ..config import Settings
from ..db import ping
from ..security.rbac import require_admin
from ..security.sessions import SessionUser
from .deps import client_ip, get_db, get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    return {"status": "ok", "version": __version__, "mongo": "ok" if ping(db) else "down",
            "simulation": settings.simulate_devices, "demo": settings.demo_mode}


@router.get("/health/request-info")
def request_info(request: Request, _: SessionUser = Depends(require_admin),
                 settings: Settings = Depends(get_settings)) -> dict:
    """Admins only: check after deploying that the login rate limit sees your real IP, not the proxy's.
    "client_ip" should be your own public address (compare with any "what is my IP" site)."""
    return {"peer": request.client.host if request.client else None,
            "x_forwarded_for": request.headers.getlist("x-forwarded-for"),
            "trusted_proxy_hops": settings.trusted_proxy_hops, "demo": settings.demo_mode,
            "client_ip": client_ip(request)}
