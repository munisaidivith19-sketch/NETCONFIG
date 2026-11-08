import re

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from ..errors import ApiError
from ..security.rbac import require_viewer
from ..security.sessions import SessionUser
from ..services.catalog import effective_capabilities
from .deps import get_db

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

Category = Query(None, pattern=r"^(switch|l3switch|router|ap|camera|unmanaged)$")
Slug = r"^[a-z0-9][a-z0-9-]{0,79}$"


def _out(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    doc.pop("updated_at", None)
    return doc


@router.get("/os-drivers")
def os_drivers(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> list[dict]:
    return [_out(d) for d in db.os_drivers.find({}, sort=[("name", 1)])]


@router.get("/brands")
def brands(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db),
           category: str | None = Category) -> list[dict]:
    query = {}
    if category:
        query["_id"] = {"$in": db.catalog_series.distinct("brand_id", {"category": category})}
    return [_out(b) for b in db.catalog_brands.find(query, sort=[("name", 1)])]


@router.get("/series")
def series(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db),
           brand_id: str | None = Query(None, pattern=Slug), category: str | None = Category) -> list[dict]:
    query = {k: v for k, v in {"brand_id": brand_id, "category": category}.items() if v}
    return [_out(s) for s in db.catalog_series.find(query, sort=[("name", 1)])]


@router.get("/models")
def models(
    _: SessionUser = Depends(require_viewer),
    db: Database = Depends(get_db),
    series_id: str | None = Query(None, pattern=Slug),
    brand_id: str | None = Query(None, pattern=Slug),
    category: str | None = Category,
    q: str | None = Query(None, max_length=40, pattern=r"^[A-Za-z0-9 ._+/-]*$"),
    page: int = Query(1, ge=1, le=1000),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    query: dict = {k: v for k, v in {"series_id": series_id, "brand_id": brand_id, "category": category}.items() if v}
    if q:
        query["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    total = db.catalog_models.count_documents(query)
    cursor = db.catalog_models.find(query, sort=[("brand_id", 1), ("name", 1)]).skip((page - 1) * page_size)
    return {"items": [_out(m) for m in cursor.limit(page_size)], "total": total, "page": page,
            "page_size": page_size}


@router.get("/models/{model_id}")
def model_detail(model_id: str, _: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> dict:
    if not re.fullmatch(Slug, model_id):
        raise ApiError(404, "Model not found.")
    model = db.catalog_models.find_one({"_id": model_id})
    if not model:
        raise ApiError(404, "Model not found.")
    driver = db.os_drivers.find_one({"_id": model["os_id"]})
    out = _out(model)
    out["brand"] = (db.catalog_brands.find_one({"_id": model["brand_id"]}) or {}).get("name")
    out["series"] = (db.catalog_series.find_one({"_id": model["series_id"]}) or {}).get("name")
    out["os_driver"] = _out(driver) if driver else None
    out["capabilities"] = effective_capabilities(driver, model)
    return out
