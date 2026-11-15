"""Domain exceptions and centralised FastAPI exception handlers.

Responsibility: map every failure to a stable, safe JSON error body.
Stack traces and internal details are logged, never returned to clients.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code, code, message = 404, "not_found", "Resource not found."


class ValidationFailure(AppError):
    status_code, code, message = 422, "validation_error", "Invalid input."


class ConflictError(AppError):
    status_code, code, message = 409, "conflict", "Request conflicts with current state."


class SlotUnavailableError(ConflictError):
    code, message = "slot_unavailable", "The selected time slot is no longer available."


class AuthenticationError(AppError):
    status_code, code, message = 401, "unauthenticated", "Authentication required."


class PermissionDeniedError(AppError):
    status_code, code, message = 403, "forbidden", "You do not have access to this resource."


class RateLimitError(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests. Please try again later."


class ExternalServiceError(AppError):
    status_code, code, message = 503, "service_unavailable", "A required service is unavailable."


def _body(code: str, message: str, details: object | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id_ctx.get()}}
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        level = logging.ERROR if exc.status_code >= 500 else logging.INFO
        logger.log(level, "app_error", extra={"error_category": exc.code, "operation": "handle"})
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only field locations and messages are returned; input values are omitted (may be PII).
        details = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(_body("validation_error", "Invalid request.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body("http_error", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", extra={"error_category": "unhandled"})
        return JSONResponse(_body("internal_error", AppError.message), status_code=500)
