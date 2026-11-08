from fastapi import APIRouter, Depends
from pymongo.database import Database

from .. import __version__
from ..db import ping
from .deps import get_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Database = Depends(get_db)) -> dict:
    return {"status": "ok", "version": __version__, "mongo": "ok" if ping(db) else "down"}
