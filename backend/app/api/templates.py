"""Saved templates (Phase 3B). A template only pre-fills the wizard: the plan is validated, generated and
safety-checked again for the chosen device, like any plan. Secrets are stripped before storage."""

from fastapi import APIRouter, Depends, Request
from pymongo import ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from .. import clock
from ..errors import ApiError
from ..models.common import oid
from ..models.template import TemplateCreate, TemplateUpdate
from ..security.rbac import require_engineer, require_viewer
from ..security.sessions import SessionUser
from ..services import audit
from .deps import get_db, rid

router = APIRouter(prefix="/api/templates", tags=["templates"])
MAX_TEMPLATES = 500


def _out(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "name": doc["name"], "description": doc.get("description", ""),
            "os_id": doc.get("os_id"), "plan": doc["plan"], "features": doc.get("features", []),
            "created_by": {k: str(v) for k, v in (doc.get("created_by") or {}).items()},
            "created_at": doc.get("created_at"), "updated_at": doc.get("updated_at")}


def _editable(db: Database, template_id: str, user: SessionUser) -> dict:
    doc = db.templates.find_one({"_id": oid(template_id)})
    if not doc:
        raise ApiError(404, "Template not found.")
    if doc["created_by"]["id"] != user.user_id and user.role != "admin":
        raise ApiError(403, "Only the author or an admin can change this template.")
    return doc


@router.get("")
def list_templates(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> dict:
    items = [_out(d) for d in db.templates.find({}, sort=[("name", 1)]).limit(MAX_TEMPLATES)]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
def create_template(body: TemplateCreate, request: Request, user: SessionUser = Depends(require_engineer),
                    db: Database = Depends(get_db)) -> dict:
    if db.templates.count_documents({}) >= MAX_TEMPLATES:
        raise ApiError(409, f"At most {MAX_TEMPLATES} templates; delete some first.")
    now = clock.now()
    doc = {"name": body.name, "description": body.description, "os_id": body.os_id,
           "plan": body.plan.without_secrets(), "features": body.plan.features(),
           "created_by": {"id": user.user_id, "username": user.username}, "created_at": now, "updated_at": now}
    try:
        doc["_id"] = db.templates.insert_one(doc).inserted_id
    except DuplicateKeyError as exc:
        raise ApiError(409, "A template with this name already exists.", fields={"name": "already used"}) from exc
    audit.record(db, "template.create", who=user, target={"type": "template", "id": str(doc["_id"])},
                 details={"name": body.name, "features": doc["features"]}, request_id=rid(request))
    return _out(doc)


@router.patch("/{template_id}")
def update_template(template_id: str, body: TemplateUpdate, request: Request,
                    user: SessionUser = Depends(require_engineer), db: Database = Depends(get_db)) -> dict:
    doc = _editable(db, template_id, user)
    changes: dict = {k: v for k, v in body.model_dump(exclude_unset=True, exclude={"plan"}).items()}
    if "name" in changes and changes["name"] is None:
        raise ApiError(422, "The name cannot be empty.", fields={"name": "required"})
    if changes.get("description", "") is None:
        changes["description"] = ""
    if body.plan is not None:
        changes["plan"] = body.plan.without_secrets()
        changes["features"] = body.plan.features()
    changes["updated_at"] = clock.now()
    try:
        new = db.templates.find_one_and_update({"_id": doc["_id"]}, {"$set": changes},
                                               return_document=ReturnDocument.AFTER)
    except DuplicateKeyError as exc:
        raise ApiError(409, "A template with this name already exists.", fields={"name": "already used"}) from exc
    audit.record(db, "template.update", who=user, target={"type": "template", "id": template_id},
                 details={"fields": sorted(k for k in changes if k != "updated_at")}, request_id=rid(request))
    return _out(new)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, request: Request, user: SessionUser = Depends(require_engineer),
                    db: Database = Depends(get_db)) -> None:
    doc = _editable(db, template_id, user)
    db.templates.delete_one({"_id": doc["_id"]})
    audit.record(db, "template.delete", who=user, target={"type": "template", "id": template_id},
                 details={"name": doc["name"]}, request_id=rid(request))
