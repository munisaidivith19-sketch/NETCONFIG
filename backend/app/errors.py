"""Safe, uniform error responses: no stack traces, always a request ID."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("netconfig.errors")

_DEFAULT_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    411: "length_required",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    423: "locked",
    429: "rate_limited",
    503: "service_unavailable",
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, fields: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code or _DEFAULT_CODES.get(status, "error")
        self.fields = fields


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def error_body(status: int, message: str, rid: str, code: str | None = None, fields: dict | None = None) -> dict:
    err = {"code": code or _DEFAULT_CODES.get(status, "error"), "message": message, "request_id": rid}
    if fields:
        err["fields"] = fields
    return {"error": err}


def field_path(loc: tuple) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(parts) or "request"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(
            error_body(exc.status, exc.message, request_id(request), exc.code, exc.fields), status_code=exc.status
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(error_body(exc.status_code, message, request_id(request)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for e in exc.errors():
            fields.setdefault(field_path(tuple(e.get("loc", ()))), e.get("msg", "invalid"))
        return JSONResponse(
            error_body(422, "Some fields are not valid.", request_id(request), fields=fields), status_code=422
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Log the type only: exception messages can contain user input or device output.
        log.error("Unhandled %s on %s %s [%s]", type(exc).__name__, request.method, request.url.path,
                  request_id(request))
        return JSONResponse(
            error_body(500, "Internal error. Quote the request ID when reporting it.", request_id(request),
                       "internal_error"),
            status_code=500,
        )
