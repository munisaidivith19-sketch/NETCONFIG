from fastapi import APIRouter, Depends, Request, Response
from pymongo.database import Database

from .. import clock
from ..config import Settings
from ..errors import ApiError
from ..models.user import LoginRequest, PasswordChange, UserOut, user_out
from ..security import sessions
from ..security.passwords import verify_password
from ..security.rbac import require_viewer
from ..security.sessions import SessionUser
from ..services import audit
from ..services.users import authenticate, set_password
from .deps import client_ip, get_db, get_settings, rid

router = APIRouter(prefix="/api/auth", tags=["auth"])

GENERIC_FAILURE = "Wrong username or password, or the account is temporarily locked."
WRONG_CURRENT = "Does not match your current password."


def _set_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response,
          db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> UserOut:
    ip = client_ip(request)
    if not request.app.state.login_limiter.allow(ip):
        audit.record(db, "auth.login", "denied", target={"type": "user", "id": body.username},
                     details={"reason": "rate_limited", "ip": ip}, request_id=rid(request))
        raise ApiError(429, "Too many sign-in attempts. Wait a minute and try again.")

    user, reason = authenticate(db, settings, body.username, body.password)
    if user is None:
        audit.record(db, "auth.login", "denied", target={"type": "user", "id": body.username},
                     details={"reason": reason, "ip": ip}, request_id=rid(request))
        if reason == "locked_now":
            audit.record(db, "auth.lockout", "ok", target={"type": "user", "id": body.username},
                         details={"minutes": settings.lockout_minutes}, request_id=rid(request))
        raise ApiError(401, GENERIC_FAILURE, code="invalid_credentials")

    token = sessions.create(db, settings, user, ip, request.headers.get("user-agent", ""))
    _set_cookie(response, settings, token)
    who = SessionUser("-", user["_id"], user["username"], user["role"])
    audit.record(db, "auth.login", "ok", who=who, details={"ip": ip}, request_id=rid(request))
    return user_out(user, clock.now())


@router.post("/logout")
def logout(request: Request, response: Response, user: SessionUser = Depends(require_viewer),
           db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    sessions.revoke(db, user.session_id)
    response.delete_cookie(settings.session_cookie, path="/", httponly=True, samesite="strict",
                           secure=settings.cookie_secure)
    audit.record(db, "auth.logout", who=user, request_id=rid(request))
    return {"ok": True}


@router.get("/me")
def me(user: SessionUser = Depends(require_viewer), db: Database = Depends(get_db)) -> UserOut:
    doc = db.users.find_one({"_id": user.user_id})
    if doc is None:
        raise ApiError(401, "Please sign in.")
    return user_out(doc, clock.now())


@router.post("/password")
def change_password(body: PasswordChange, request: Request, user: SessionUser = Depends(require_viewer),
                    db: Database = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict:
    doc = db.users.find_one({"_id": user.user_id})
    if doc is None or not verify_password(body.current_password, doc.get("password_hash")):
        audit.record(db, "auth.password_change", "denied", who=user, request_id=rid(request))
        raise ApiError(400, "The current password is wrong.", fields={"current_password": WRONG_CURRENT})
    set_password(db, settings, doc, body.new_password)
    ended = sessions.revoke_all_for_user(db, user.user_id, except_session=user.session_id)
    audit.record(db, "auth.password_change", who=user, details={"other_sessions_ended": ended},
                 request_id=rid(request))
    return {"ok": True}
