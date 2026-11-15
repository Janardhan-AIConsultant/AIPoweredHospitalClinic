"""ASGI middleware: request id, access log with duration, body size limit, security headers."""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import request_id_ctx

logger = logging.getLogger("app.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_request_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max = max_request_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if 8 <= len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        try:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self._max:
                response: Response = JSONResponse(
                    {
                        "error": {
                            "code": "payload_too_large",
                            "message": "Request body too large.",
                            "request_id": rid,
                        }
                    },
                    status_code=413,
                )
            else:
                response = await call_next(request)
            for key, value in SECURITY_HEADERS.items():
                response.headers.setdefault(key, value)
            response.headers["X-Request-ID"] = rid
            logger.info(
                "request",
                extra={
                    "operation": f"{request.method} {request.url.path}",
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                },
            )
            return response
        finally:
            request_id_ctx.reset(token)
