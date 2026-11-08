"""Role checks for every route (deny by default).

Every /api route must depend on ``require_role(...)`` or be listed in ``PUBLIC_ROUTES``.
``assert_all_routes_protected`` runs when the app is created, so a new route that forgets
authentication stops the app from starting instead of silently being public.
"""

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.routing import APIRoute

from ..errors import ApiError
from .sessions import SessionUser, resolve

ROLES = ("viewer", "engineer", "admin")
RANK = {role: i for i, role in enumerate(ROLES)}

PUBLIC_ROUTES = {("GET", "/api/health"), ("POST", "/api/auth/login")}


def current_user(request: Request) -> SessionUser:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie)
    user = resolve(request.app.state.db, settings, token)
    if user is None:
        raise ApiError(401, "Please sign in.")
    request.state.user = user
    return user


def require_role(minimum: str) -> Callable[..., SessionUser]:
    if minimum not in RANK:
        raise ValueError(f"unknown role {minimum}")

    def dependency(user: SessionUser = Depends(current_user)) -> SessionUser:
        if RANK.get(user.role, -1) < RANK[minimum]:
            raise ApiError(403, "Your role does not allow this action.")
        return user

    dependency.ncs_role = minimum  # type: ignore[attr-defined]
    return dependency


require_viewer = require_role("viewer")
require_engineer = require_role("engineer")
require_admin = require_role("admin")


def _roles_in(dependant) -> list[str]:
    found = []
    call = getattr(dependant, "call", None)
    if call is not None and hasattr(call, "ncs_role"):
        found.append(call.ncs_role)
    for sub in dependant.dependencies:
        found.extend(_roles_in(sub))
    return found


def route_role(route: APIRoute) -> str | None:
    roles = _roles_in(route.dependant)
    return max(roles, key=RANK.__getitem__) if roles else None


def iter_api_routes(routers):
    """Yield (method, path, route) for every route of the given APIRouters.

    We walk our own routers rather than ``app.routes``: FastAPI wraps included routers in private
    classes whose layout changes between versions. Anything we cannot inspect fails closed.
    """
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                raise RuntimeError(f"Cannot check the role of route {route!r}; nested routers are not supported.")
            for method in sorted(route.methods):
                yield method, route.path, route


def assert_all_routes_protected(routers) -> None:
    unprotected = [
        f"{method} {path}"
        for method, path, route in iter_api_routes(routers)
        if (method, path) not in PUBLIC_ROUTES and route_role(route) is None
    ]
    if unprotected:
        raise RuntimeError("Routes without a role check: " + ", ".join(sorted(unprotected)))
