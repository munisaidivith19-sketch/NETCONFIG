"""App factory: middleware, routers, static frontend, startup and shutdown."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, errors
from .api import audit as audit_api
from .api import auth, catalog, devices, health, hostkeys, jobs, plans, users
from .config import Settings
from .db import connect, ensure_indexes
from .errors import ApiError
from .security.guard import LocalhostGuard
from .security.ratelimit import RateLimiter
from .security.rbac import assert_all_routes_protected
from .services.catalog import seed_if_empty
from .services.jobs import JobRunner

log = logging.getLogger("netconfig")

ROUTERS = [health.router, auth.router, users.router, audit_api.router, catalog.router, devices.router, plans.router,
           jobs.router, hostkeys.router]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.check_bind_address()
    settings.check_simulation()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            ensure_indexes(app.state.db)
            seed_if_empty(app.state.db)
            app.state.runner.start()  # crash recovery + approval expiry sweep
        except Exception as exc:  # noqa: BLE001 - app still starts; /api/health reports "down"
            log.warning("MongoDB not available at startup (%s); /api/health will report it.", type(exc).__name__)
        if settings.simulate_devices:
            log.warning("SIMULATE_DEVICES=true: pushes go to simulated devices, not the network.")
        if settings.allow_remote:
            log.warning("ALLOW_REMOTE=true: NetConfig Studio is reachable from the network. Use HTTPS.")
        yield
        app.state.runner.shutdown()
        app.state.mongo.close()

    docs = not settings.is_production
    app = FastAPI(
        title="NetConfig Studio",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.mongo = connect(settings)
    app.state.db = app.state.mongo[settings.mongo_db]
    app.state.login_limiter = RateLimiter(settings.login_rate_per_minute, 60)
    app.state.runner = JobRunner(app.state.db, settings)

    errors.install(app)
    assert_all_routes_protected(ROUTERS)
    for router in ROUTERS:
        app.include_router(router)

    _mount_frontend(app, settings.frontend_dist)
    app.add_middleware(LocalhostGuard, settings=settings)
    return app


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built React app from the same origin, with SPA fallback to index.html."""
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        first = path.split("/", 1)[0]
        if first in ("api", "docs", "redoc", "openapi.json"):
            raise ApiError(404, "Not found.")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)
