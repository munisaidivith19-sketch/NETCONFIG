import re

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from pymongo.collation import Collation
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import clock
from ..errors import ApiError, field_path
from ..models.common import oid
from ..models.device import PRODUCTION_TAG, DeviceCreate, DeviceOut, DeviceUpdate
from ..security.rbac import RANK, require_admin, require_engineer, require_viewer
from ..security.sessions import SessionUser
from ..services import audit
from ..services.catalog import effective_capabilities
from .deps import get_db, rid

router = APIRouter(prefix="/api/devices", tags=["devices"])
CI = Collation(locale="en", strength=2)


def _device_out(db: Database, doc: dict, cache: dict | None = None) -> DeviceOut:
    cache = cache if cache is not None else {}

    def lookup(coll: str, key: str | None):
        if key is None:
            return None
        if (coll, key) not in cache:
            cache[(coll, key)] = db[coll].find_one({"_id": key})
        return cache[(coll, key)]

    model = lookup("catalog_models", doc.get("model_id")) or {}
    driver = lookup("os_drivers", doc.get("os_id")) or {}
    brand = lookup("catalog_brands", model.get("brand_id")) or {}
    return DeviceOut(
        id=str(doc["_id"]), name=doc["name"], model_id=doc["model_id"], model_name=model.get("name"),
        brand=brand.get("name"), category=model.get("category"), os_id=doc.get("os_id"),
        os_name=driver.get("name"), support=driver.get("support"),
        capabilities=effective_capabilities(driver, model), mgmt_ip=doc.get("mgmt_ip"),
        connection=doc.get("connection", {}), location=doc.get("location", ""), tags=doc.get("tags", []),
        production=PRODUCTION_TAG in doc.get("tags", []), status=doc.get("status", {}),
        created_at=doc.get("created_at"), updated_at=doc.get("updated_at"),
    )


def _check_model(db: Database, body: DeviceCreate) -> dict:
    model = db.catalog_models.find_one({"_id": body.model_id})
    if not model:
        raise ApiError(422, "Unknown catalog model.", fields={"model_id": "not in the catalog"})
    driver = db.os_drivers.find_one({"_id": model["os_id"]}) or {}
    allowed = set(driver.get("connections", [])) or {"none"}
    if body.connection.method not in allowed:
        raise ApiError(422, "This device does not support that connection method.",
                       fields={"connection.method": f"use one of: {', '.join(sorted(allowed))}"})
    return model


def _check_production_change(user: SessionUser, before: list[str], after: list[str]) -> None:
    """Only admins may add or remove the production tag: it controls two-person approval."""
    if (PRODUCTION_TAG in before) != (PRODUCTION_TAG in after) and RANK[user.role] < RANK["admin"]:
        raise ApiError(403, "Only an admin can add or remove the production tag.",
                       fields={"tags": "production tag needs an admin"})


def _validation_error(exc: ValidationError) -> ApiError:
    fields = {}
    for e in exc.errors():
        fields.setdefault(field_path(tuple(e.get("loc", ()))), e.get("msg", "invalid").removeprefix("Value error, "))
    return ApiError(422, "Some fields are not valid.", fields=fields)


def _save_conflict(exc: DuplicateKeyError) -> ApiError:
    field = "mgmt_ip" if "mgmt_ip" in str(exc) else "name"
    return ApiError(409, f"Another device already uses this {'IP address' if field == 'mgmt_ip' else 'name'}.",
                    fields={field: "already in use"})


@router.get("")
def list_devices(
    _: SessionUser = Depends(require_viewer),
    db: Database = Depends(get_db),
    tag: str | None = Query(None, pattern=r"^[a-z0-9][a-z0-9-]{0,23}$"),
    os_id: str | None = Query(None, pattern=r"^[a-z0-9_]{1,40}$"),
    category: str | None = Query(None, pattern=r"^(switch|l3switch|router|ap|camera|unmanaged)$"),
    q: str | None = Query(None, max_length=63, pattern=r"^[A-Za-z0-9._:-]*$"),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    query: dict = {}
    if tag:
        query["tags"] = tag
    if os_id:
        query["os_id"] = os_id
    if category:
        query["model_id"] = {"$in": db.catalog_models.distinct("_id", {"category": category})}
    if q:
        pattern = re.escape(q)
        query["$or"] = [{"name": {"$regex": pattern, "$options": "i"}}, {"mgmt_ip": {"$regex": "^" + pattern}}]
    total = db.devices.count_documents(query)
    cursor = db.devices.find(query, sort=[("name", 1)], collation=CI).skip((page - 1) * page_size).limit(page_size)
    cache: dict = {}
    return {"items": [_device_out(db, d, cache) for d in cursor], "total": total, "page": page,
            "page_size": page_size}


@router.post("", status_code=201)
def create_device(body: DeviceCreate, request: Request, user: SessionUser = Depends(require_engineer),
                  db: Database = Depends(get_db)) -> DeviceOut:
    model = _check_model(db, body)
    _check_production_change(user, [], body.tags)
    now = clock.now()
    doc = {**body.model_dump(), "os_id": model["os_id"], "status": {"reachable": None, "checked_at": None},
           "created_by": user.user_id, "created_at": now, "updated_at": now}
    try:
        doc["_id"] = db.devices.insert_one(doc).inserted_id
    except DuplicateKeyError as exc:
        raise _save_conflict(exc) from exc
    audit.record(db, "device.create", who=user, target={"type": "device", "id": str(doc["_id"])},
                 details={"name": body.name, "model_id": body.model_id, "mgmt_ip": body.mgmt_ip,
                          "tags": body.tags}, request_id=rid(request))
    return _device_out(db, doc)


@router.get("/{device_id}")
def get_device(device_id: str, _: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> DeviceOut:
    doc = db.devices.find_one({"_id": oid(device_id)})
    if not doc:
        raise ApiError(404, "Device not found.")
    return _device_out(db, doc)


@router.patch("/{device_id}")
def update_device(device_id: str, body: DeviceUpdate, request: Request,
                  user: SessionUser = Depends(require_engineer), db: Database = Depends(get_db)) -> DeviceOut:
    doc = db.devices.find_one({"_id": oid(device_id)})
    if not doc:
        raise ApiError(404, "Device not found.")
    changes = body.model_dump(exclude_unset=True)
    current = {k: doc.get(k) for k in DeviceCreate.model_fields}
    merged = {**current, **changes}
    try:
        validated = DeviceCreate.model_validate(merged)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    model = _check_model(db, validated)
    _check_production_change(user, doc.get("tags", []), validated.tags)
    update = {**validated.model_dump(), "os_id": model["os_id"], "updated_at": clock.now()}
    try:
        db.devices.update_one({"_id": doc["_id"]}, {"$set": update})
    except DuplicateKeyError as exc:
        raise _save_conflict(exc) from exc
    audit.record(db, "device.update", who=user, target={"type": "device", "id": device_id},
                 details={"fields": sorted(changes)}, request_id=rid(request))
    return _device_out(db, db.devices.find_one({"_id": doc["_id"]}))


@router.delete("/{device_id}")
def delete_device(device_id: str, request: Request, user: SessionUser = Depends(require_admin),
                  db: Database = Depends(get_db)) -> dict:
    doc = db.devices.find_one({"_id": oid(device_id)})
    if not doc:
        raise ApiError(404, "Device not found.")
    db.devices.delete_one({"_id": doc["_id"]})
    audit.record(db, "device.delete", who=user, target={"type": "device", "id": device_id},
                 details={"name": doc["name"]}, request_id=rid(request))
    return {"ok": True}
