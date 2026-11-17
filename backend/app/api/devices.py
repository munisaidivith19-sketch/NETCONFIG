import re

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from pymongo.collation import Collation
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import clock
from ..errors import ApiError, field_path
from ..models.common import oid
from ..models.device import PRODUCTION_TAG, DeviceCreate, DeviceOut, DeviceUpdate, DiscoverRequest, OnvifRequest
from ..security.ratelimit import RateLimiter
from ..security.rbac import RANK, require_admin, require_engineer, require_viewer
from ..security.sessions import SessionUser
from ..services import audit, discovery, onvif
from ..services.catalog import effective_capabilities
from .deps import get_db, rid

router = APIRouter(prefix="/api/devices", tags=["devices"])
CI = Collation(locale="en", strength=2)
UPLINK_CATEGORIES = ("ap", "camera")
onvif_limit = RateLimiter(limit=10, window_seconds=60)
discover_limit = RateLimiter(limit=10, window_seconds=60)


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
        uplink=doc.get("uplink"), facts=doc.get("facts"), neighbors=doc.get("neighbors"), vlans=doc.get("vlans"),
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


def _check_uplink(db: Database, body: DeviceCreate, model: dict, self_id=None) -> None:
    """An uplink points at a switch port in the inventory, and only APs and cameras have one."""
    if body.uplink is None:
        return
    if model.get("category") not in UPLINK_CATEGORIES:
        raise ApiError(422, "Only access points and cameras have an uplink switch port.", fields={"uplink": "not used"})
    switch = db.devices.find_one({"_id": oid(body.uplink.device_id)})
    switch_model = db.catalog_models.find_one({"_id": switch["model_id"]}) if switch else None
    if not switch or switch["_id"] == self_id or (switch_model or {}).get("category") not in ("switch", "l3switch"):
        raise ApiError(422, "The uplink must be a switch in the inventory.",
                       fields={"uplink.device_id": "not a switch"})
    pattern = switch_model.get("port_pattern") or ""
    if pattern and not re.fullmatch(pattern, body.uplink.interface):
        examples = ", ".join(switch_model.get("port_examples", []))
        raise ApiError(422, "That port does not exist on the switch model.",
                       fields={"uplink.interface": f"use the full port name, e.g. {examples}"})


def _check_production_change(user: SessionUser, before: list[str], after: list[str]) -> None:
    """Only admins may add or remove the production tag: it controls two-person approval."""
    if (PRODUCTION_TAG in before) != (PRODUCTION_TAG in after) and RANK[user.role] < RANK["admin"]:
        raise ApiError(403, "Only an admin can add or remove the production tag.",
                       fields={"tags": "production tag needs an admin"})


def _check_production_target(user: SessionUser, doc: dict, changes: dict) -> None:
    """On a production device, where it is (address, connection) and what it is (model) are admin-only too.
    Otherwise an engineer could move its address to an untagged record and push to it without approval."""
    moved = {k for k in ("mgmt_ip", "connection", "model_id") if k in changes and changes[k] != doc.get(k)}
    if moved and PRODUCTION_TAG in doc.get("tags", []) and RANK[user.role] < RANK["admin"]:
        raise ApiError(403, "Only an admin can change the address, connection or model of a production device.",
                       fields={k: "production device: needs an admin" for k in sorted(moved)})


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
    # The list leaves out the discovered VLAN and neighbour tables (up to 4094 + 256 rows per device); they are
    # read with GET /devices/{id}.
    cursor = db.devices.find(query, {"vlans": 0, "neighbors": 0}, sort=[("name", 1)], collation=CI) \
        .skip((page - 1) * page_size).limit(page_size)
    cache: dict = {}
    return {"items": [_device_out(db, d, cache) for d in cursor], "total": total, "page": page,
            "page_size": page_size}


@router.post("", status_code=201)
def create_device(body: DeviceCreate, request: Request, user: SessionUser = Depends(require_engineer),
                  db: Database = Depends(get_db)) -> DeviceOut:
    model = _check_model(db, body)
    _check_uplink(db, body, model)
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
    _check_uplink(db, validated, model, self_id=doc["_id"])
    _check_production_change(user, doc.get("tags", []), validated.tags)
    _check_production_target(user, doc, {k: v for k, v in validated.model_dump().items() if k in changes})
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
    # APs and cameras plugged into this switch lose their uplink; a stale one would fail every later edit of them.
    cleared = db.devices.update_many({"uplink.device_id": str(doc["_id"])}, {"$unset": {"uplink": ""}}).modified_count
    audit.record(db, "device.delete", who=user, target={"type": "device", "id": device_id},
                 details={"name": doc["name"], "uplinks_cleared": cleared}, request_id=rid(request))
    return {"ok": True}


@router.post("/{device_id}/discover")
def discover_device(device_id: str, body: DiscoverRequest, request: Request,
                    user: SessionUser = Depends(require_engineer), db: Database = Depends(get_db)) -> DeviceOut:
    """Read facts, neighbours and VLANs with read-only show commands. The login is used for this request only."""
    doc = db.devices.find_one({"_id": oid(device_id)})
    if not doc:
        raise ApiError(404, "Device not found.")
    if not discover_limit.allow(user.user_id):
        raise ApiError(429, "Too many device reads; wait a minute.")
    runner = request.app.state.runner
    lock = runner.device_locks[str(doc["_id"])]
    if not lock.acquire(blocking=False):
        raise ApiError(409, "A job is running on this device; read its facts when it has finished.")
    target = {"type": "device", "id": device_id}
    login = discovery.Login(body.username, body.password, body.enable_secret)
    try:
        found = discovery.discover(db, runner.connector, request.app.state.settings, doc, login, who=user)
    except discovery.DiscoveryError as exc:
        audit.record(db, "device.discover", who=user, target=target, result="failed", details={"error": str(exc)},
                     request_id=rid(request))
        raise ApiError(exc.status, str(exc)) from exc
    finally:
        lock.release()
        del login
    notes = found.pop("notes")
    db.devices.update_one({"_id": doc["_id"]}, {"$set": found})
    audit.record(db, "device.discover", who=user, target=target, request_id=rid(request),
                 details={"model_match": found["facts"]["match"]["status"], "neighbors": len(found["neighbors"]),
                          "notes": notes[:3]})
    return _device_out(db, db.devices.find_one({"_id": doc["_id"]}))


@router.post("/{device_id}/onvif")
def read_onvif(device_id: str, body: OnvifRequest, request: Request, user: SessionUser = Depends(require_engineer),
               db: Database = Depends(get_db)) -> DeviceOut:
    """Read a camera's ONVIF device information (read only). The login is used for this request only."""
    doc = db.devices.find_one({"_id": oid(device_id)})
    if not doc:
        raise ApiError(404, "Device not found.")
    model = db.catalog_models.find_one({"_id": doc["model_id"]}) or {}
    if model.get("category") != "camera" or not doc.get("mgmt_ip"):
        raise ApiError(422, "ONVIF information can only be read from a camera with a management address.")
    if not onvif_limit.allow(user.user_id):
        raise ApiError(429, "Too many camera requests; wait a minute.")
    target = {"type": "device", "id": device_id}
    try:
        info = onvif.get_device_information(doc["mgmt_ip"], body.port, body.username, body.password)
    except onvif.OnvifError as exc:
        audit.record(db, "device.onvif_read", who=user, target=target, result="failed",
                     details={"error": str(exc)}, request_id=rid(request))
        raise ApiError(502, str(exc)) from exc
    facts = {"source": "onvif", "read_at": clock.now(), **{k.lower(): v for k, v in info.items()}}
    db.devices.update_one({"_id": doc["_id"]}, {"$set": {"facts": facts}})
    audit.record(db, "device.onvif_read", who=user, target=target, details={"port": body.port},
                 request_id=rid(request))
    return _device_out(db, db.devices.find_one({"_id": doc["_id"]}))
