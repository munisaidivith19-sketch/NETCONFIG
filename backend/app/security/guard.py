"""Localhost guard (CLAUDE.md 8.1).

A web page on *any* site can make the engineer's browser send requests to 127.0.0.1. Two attacks
matter for a local app:

* DNS rebinding – evil.com is re-pointed to 127.0.0.1, so the browser treats our API as
  "same origin" with evil.com. The Host header still says ``evil.com``, so a Host allowlist stops it.
* CSRF to localhost – a form or fetch from evil.com posts to http://127.0.0.1:8000. We require an
  allowed ``Origin`` and a custom ``X-Requested-With`` header. A cross-site page can only add a custom
  header after a CORS preflight, and we never answer preflights, so it cannot send one.
"""

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import Settings
from ..errors import error_body

CUSTOM_HEADER = "x-requested-with"
CUSTOM_HEADER_VALUE = "NetConfigStudio"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# Swagger UI (dev only) loads from a CDN and uses an inline script.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'"
)
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def security_headers(path: str) -> list[tuple[bytes, bytes]]:
    csp = DOCS_CSP if path.startswith(DOCS_PATHS) else CSP
    headers = [
        (b"content-security-policy", csp.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-opener-policy", b"same-origin"),
        (b"cross-origin-resource-policy", b"same-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), serial=()"),
    ]
    if path.startswith("/api/"):
        headers.append((b"cache-control", b"no-store"))
    return headers


class LocalhostGuard:
    """Pure ASGI middleware: request ID, Host/Origin/custom-header checks, body limit, headers."""

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = secrets.token_hex(8)
        scope.setdefault("state", {})["request_id"] = rid
        path = scope.get("path", "")
        extra = security_headers(path) + [(b"x-request-id", rid.encode())]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        problem = self.check(scope)
        if problem:
            status, message = problem
            response = JSONResponse(error_body(status, message, rid), status_code=status)
            await response(scope, receive, send_with_headers)
            return

        await self.app(scope, receive, send_with_headers)

    def check(self, scope: Scope) -> tuple[int, str] | None:
        headers = Headers(scope=scope)
        host = headers.get("host", "").lower()
        if host not in self.settings.allowed_hosts:
            return 400, "Host not allowed."

        method = scope["method"]
        if method == "OPTIONS":
            # No CORS: we never answer preflights, so cross-site pages cannot send custom headers.
            return 403, "Cross-origin requests are not allowed."
        if method not in UNSAFE_METHODS:
            return None

        origin = headers.get("origin")
        if origin is not None and origin not in self.settings.allowed_origins:
            return 403, "Origin not allowed."
        if headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            # Dev: the Vite proxy forwards requests, so the browser still sees same-origin.
            return 403, "Cross-site request blocked."
        if headers.get(CUSTOM_HEADER) != CUSTOM_HEADER_VALUE:
            return 403, "Missing required request header."

        if "chunked" in headers.get("transfer-encoding", "").lower():
            return 411, "Content-Length required."
        length = headers.get("content-length")
        if length:
            if not length.isdigit():
                return 400, "Invalid Content-Length."
            if int(length) > self.settings.max_body_bytes:
                return 413, "Request body too large."
            if int(length) > 0:
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    return 415, "Content-Type must be application/json."
        return None
