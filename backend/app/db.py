"""MongoDB client and index creation."""

import logging

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collation import Collation
from pymongo.database import Database

from .config import Settings

log = logging.getLogger(__name__)


def connect(settings: Settings) -> MongoClient:
    return MongoClient(
        settings.mongo_uri,
        tz_aware=True,
        serverSelectionTimeoutMS=settings.mongo_timeout_ms,
        connectTimeoutMS=settings.mongo_timeout_ms,
        appname="netconfig-studio",
    )


def ping(db: Database) -> bool:
    try:
        db.client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001 - any failure means "down" for /health
        return False


def ensure_indexes(db: Database) -> None:
    ci = Collation(locale="en", strength=2)  # case-insensitive usernames

    db.users.create_index([("username", ASCENDING)], unique=True, collation=ci)

    db.sessions.create_index([("expires_at", ASCENDING)], expireAfterSeconds=0)
    db.sessions.create_index([("user_id", ASCENDING)])

    db.audit_log.create_index([("seq", ASCENDING)], unique=True)
    db.audit_log.create_index([("at", DESCENDING)])
    db.audit_log.create_index([("action", ASCENDING), ("at", DESCENDING)])
    db.audit_log.create_index([("who.user_id", ASCENDING), ("at", DESCENDING)])

    db.catalog_series.create_index([("brand_id", ASCENDING), ("category", ASCENDING)])
    db.catalog_models.create_index([("series_id", ASCENDING)])
    db.catalog_models.create_index([("category", ASCENDING), ("brand_id", ASCENDING)])
    db.catalog_models.create_index([("name", "text")])

    db.devices.create_index([("name", ASCENDING)], unique=True, collation=ci)
    db.devices.create_index(
        [("mgmt_ip", ASCENDING)],
        unique=True,
        partialFilterExpression={"mgmt_ip": {"$type": "string"}},
    )
    db.devices.create_index([("tags", ASCENDING)])
    db.devices.create_index([("os_id", ASCENDING)])

    db.jobs.create_index([("created_at", DESCENDING)])
    db.jobs.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
    db.jobs.create_index([("status", ASCENDING), ("approval.expires_at", ASCENDING)])
    db.jobs.create_index([("steps.device_id", ASCENDING), ("created_at", DESCENDING)])
    db.jobs.create_index([("requested_by", ASCENDING)])

    db.host_keys.create_index([("host", ASCENDING), ("port", ASCENDING)], unique=True)
    db.templates.create_index([("name", ASCENDING)], unique=True, collation=ci)
    log.info("MongoDB indexes ensured on %s", db.name)
