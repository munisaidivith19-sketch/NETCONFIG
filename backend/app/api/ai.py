"""AI assistant endpoints (Phase 5A). Engineers only; a draft is returned to the form and goes through the normal
preview, safety checks and approval. Nothing here creates or runs a job."""

import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import StringConstraints

from ..config import Settings
from ..errors import ApiError
from ..models.common import StrictModel
from ..security.ratelimit import RateLimiter
from ..security.rbac import require_engineer, require_viewer
from ..security.sessions import SessionUser
from ..services import ai, audit
from .deps import get_db, get_settings, rid

router = APIRouter(prefix="/api/ai", tags=["ai"])
# Each call uses the provider's free-tier quota (or the PC's CPU for Ollama): drafts and explanations share one limit.
ai_limit = RateLimiter(limit=10, window_seconds=60)


def _limited(user: SessionUser) -> None:
    if not ai_limit.allow(user.user_id):
        raise ApiError(429, "Too many AI requests; wait a minute.")


class DraftRequest(StrictModel):
    description: Annotated[str, StringConstraints(min_length=10, max_length=2000)]


class ExplainRequest(StrictModel):
    kind: Literal["commands", "verification", "diff"]
    text: Annotated[str, StringConstraints(min_length=1, max_length=ai.MAX_INPUT_CHARS)]


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@router.get("/status")
def ai_status(_: SessionUser = Depends(require_viewer), settings: Settings = Depends(get_settings)) -> dict:
    return ai.status(settings)


@router.post("/draft")
def ai_draft(body: DraftRequest, request: Request, user: SessionUser = Depends(require_engineer),
             settings: Settings = Depends(get_settings), db=Depends(get_db)) -> dict:
    _limited(user)
    plan, dropped = ai.draft(settings, body.description)
    # The audit entry holds a hash and sizes, never the text itself.
    audit.record(db, "ai.draft", who=user, request_id=rid(request),
                 details={"chars": len(body.description), "sha256": _digest(body.description),
                          "provider": settings.ai_provider})
    return {"plan": plan.without_secrets(), "features": plan.features(), "dropped": dropped,
            "notice": "AI draft: check every value. It is validated and previewed like a manual plan."}


@router.post("/explain")
def ai_explain(body: ExplainRequest, request: Request, user: SessionUser = Depends(require_engineer),
               settings: Settings = Depends(get_settings), db=Depends(get_db)) -> dict:
    _limited(user)
    text = ai.explain(settings, body.kind, body.text)
    audit.record(db, "ai.explain", who=user, request_id=rid(request),
                 details={"kind": body.kind, "chars": len(body.text), "sha256": _digest(body.text),
                          "provider": settings.ai_provider})
    return {"text": text}
