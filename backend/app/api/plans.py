from fastapi import APIRouter, Depends, Request
from pymongo.database import Database

from ..config import Settings
from ..models.plan import PreviewRequest
from ..security.rbac import require_engineer
from ..security.sessions import SessionUser
from ..services import audit, planning
from .deps import get_db, get_settings, rid

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.post("/preview")
def preview(body: PreviewRequest, request: Request, user: SessionUser = Depends(require_engineer),
            db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """Validate a plan for one device (or catalog model) and return the masked commands.

    Nothing is sent to a device. Secrets in the plan are masked in the response and are never stored.
    """
    p = planning.prepare(db, settings, body.plan, device_id=body.device_id, model_id=body.model_id)
    target = ({"type": "device", "id": str(p.device["_id"]), "name": p.device["name"]} if p.device
              else {"type": "model", "id": p.model["_id"]})
    audit.record(db, "plan.preview", result="ok" if p.ok else "invalid", who=user, target=target,
                 details={"features": p.plan.features(), "commands": len(p.commands),
                          "commands_hash": p.commands_hash if p.ok else None, "errors": len(p.errors)},
                 request_id=rid(request))
    if p.ok and p.plan.custom_commands:
        custom = p.commands[-len(p.plan.custom_commands):]  # already masked
        audit.record(db, "plan.custom_commands", who=user, target=target,
                     details={"commands": custom, "hash": planning.commands_hash(custom)}, request_id=rid(request))
    driver = p.driver
    return {
        "ok": p.ok,
        "errors": p.errors,
        "warnings": p.warnings,
        "unsupported": p.unsupported,
        "commands": p.commands,
        "verify_commands": p.verify_commands,
        "commands_hash": p.commands_hash if p.ok else None,
        "driver": {"os_id": p.driver_doc["_id"], "name": p.driver_doc.get("name"),
                   "support": p.driver_doc.get("support")},
        "rollback": driver.rollback_strategy() if driver else None,
        "revert_minutes": p.plan.revert_minutes,
        "save_command": driver.save_command() if driver and p.plan.save else None,
        "production": p.production,
    }
