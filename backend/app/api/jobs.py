from fastapi import APIRouter, Depends, Query, Request
from pymongo.database import Database

from ..config import Settings
from ..models.common import ObjectIdStr, oid
from ..models.job import STATUSES, JobCreate, RejectRequest, RunRequest
from ..security.rbac import RANK, require_admin, require_engineer, require_viewer
from ..security.sessions import SessionUser
from ..services import audit, jobs
from .deps import get_db, get_settings, rid

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
STATUS_PATTERN = "^(" + "|".join(STATUSES) + ")$"


def runner(request: Request) -> jobs.JobRunner:
    return request.app.state.runner


@router.post("", status_code=201)
def create_job(body: JobCreate, request: Request, user: SessionUser = Depends(require_engineer),
               db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """Create a job (see JobCreate for the four kinds). No credentials here: they are given to /run, after any
    approval."""
    return jobs.job_out(jobs.create(db, settings, user, body, rid(request)))


@router.post("/preview")
def preview_job(body: JobCreate, request: Request, user: SessionUser = Depends(require_engineer),
                db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    """Preview any job kind (one device, several switches, router link, console bootstrap). Nothing is sent
    to a device and nothing is stored except the audit entry."""
    out = jobs.preview(db, settings, body)
    audit.record(db, "plan.preview", result="ok" if out["ok"] else "invalid", who=user,
                 target={"type": "job_preview", "id": body.kind},
                 details={"kind": body.kind, "devices": [s["device_name"] for s in out["steps"]],
                          "commands_hash": [s["commands_hash"] for s in out["steps"]], "errors": len(out["errors"])},
                 request_id=rid(request))
    return out


@router.get("")
def list_jobs(_: SessionUser = Depends(require_viewer), db: Database = Depends(get_db),
              status: str | None = Query(None, pattern=STATUS_PATTERN),
              device_id: ObjectIdStr | None = Query(None),
              kind: str | None = Query(None, pattern="^(push|multi|link|bootstrap)$"),
              page: int = Query(1, ge=1, le=1000), page_size: int = Query(25, ge=1, le=100)) -> dict:
    jobs.expire_sweep(db)
    query: dict = {}
    if status:
        query["status"] = status
    if device_id:
        query["steps.device_id"] = oid(device_id)
    if kind:
        query["kind"] = kind
    total = db.jobs.count_documents(query)
    cursor = db.jobs.find(query, jobs.LIST_PROJECTION, sort=[("created_at", -1)],
                          skip=(page - 1) * page_size, limit=page_size)
    return {"items": [jobs.job_out(d) for d in cursor], "total": total, "page": page, "page_size": page_size}


@router.get("/{job_id}")
def get_job(job_id: str, user: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> dict:
    jobs.expire_sweep(db)
    # The running-config backup is masked, but a whole device config is more than read-only users need.
    return jobs.job_out(jobs.get(db, job_id), backup=RANK.get(user.role, -1) >= RANK["engineer"])


@router.post("/{job_id}/approve")
def approve_job(job_id: str, request: Request, user: SessionUser = Depends(require_admin),
                db: Database = Depends(get_db)) -> dict:
    return jobs.job_out(jobs.approve(db, user, job_id, rid(request)))


@router.post("/{job_id}/reject")
def reject_job(job_id: str, body: RejectRequest, request: Request, user: SessionUser = Depends(require_admin),
               db: Database = Depends(get_db)) -> dict:
    return jobs.job_out(jobs.reject(db, user, job_id, body.reason, rid(request)))


@router.post("/{job_id}/run", status_code=202)
def run_job(job_id: str, body: RunRequest, request: Request, user: SessionUser = Depends(require_engineer)) -> dict:
    """Start a ready job. The credentials in the body are kept in memory for this run only."""
    return jobs.job_out(runner(request).run(user, job_id, body, rid(request)))


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, user: SessionUser = Depends(require_engineer)) -> dict:
    return jobs.job_out(runner(request).cancel(user, job_id, rid(request)))
