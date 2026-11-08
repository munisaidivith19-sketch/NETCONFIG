"""Catalog: brands → series → models, and OS drivers. Seeded from app/data/catalog.json."""

import json
import logging
from pathlib import Path

from pymongo import ReplaceOne
from pymongo.database import Database

from .. import clock

log = logging.getLogger(__name__)
CATALOG_FILE = Path(__file__).resolve().parent.parent / "data" / "catalog.json"

COLLECTIONS = {
    "os_drivers": "os_drivers",
    "brands": "catalog_brands",
    "series": "catalog_series",
    "models": "catalog_models",
}


def load_file(path: Path = CATALOG_FILE) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def seed(db: Database, data: dict | None = None, reset: bool = False) -> dict[str, int]:
    """Upsert every catalog document. With reset=True, documents not in the file are removed."""
    data = data or load_file()
    now = clock.now()
    counts = {}
    for key, name in COLLECTIONS.items():
        docs = data.get(key, [])
        ops = [ReplaceOne({"_id": d["_id"]}, {**d, "updated_at": now}, upsert=True) for d in docs]
        if ops:
            db[name].bulk_write(ops, ordered=False)
        if reset:
            db[name].delete_many({"_id": {"$nin": [d["_id"] for d in docs]}})
        counts[key] = len(docs)
    return counts


def seed_if_empty(db: Database) -> None:
    if db.catalog_models.estimated_document_count() == 0:
        counts = seed(db)
        log.info("Seeded sample catalog: %s", counts)


def effective_capabilities(driver: dict | None, model: dict | None) -> list[str]:
    """Driver capabilities minus what the model cannot do (e.g. an L2-only switch has no OSPF)."""
    if not driver:
        return []
    excluded = set((model or {}).get("capabilities_exclude", []))
    return [c for c in driver.get("capabilities", []) if c not in excluded]
