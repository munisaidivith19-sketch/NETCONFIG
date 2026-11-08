from fastapi import APIRouter, Depends
from pymongo.database import Database

from .. import __version__
from ..config import Settings
from ..db import ping
from .deps import get_db, get_settings

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    return {"status": "ok", "version": __version__, "mongo": "ok" if ping(db) else "down",
            "simulation": settings.simulate_devices}
