"""FastAPI application factory (serverless-safe: no work at import beyond wiring)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, booking, catalog, chat, doctor_portal, health, internal, patient, whatsapp
from app.core.body_limit import BodyLimitMiddleware
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_request_bytes)  # innermost
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
    )
    app.add_middleware(RequestContextMiddleware, max_request_bytes=settings.max_request_bytes)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(booking.router)
    app.include_router(chat.router)
    app.include_router(whatsapp.router)
    app.include_router(internal.router)
    app.include_router(patient.router)
    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(doctor_portal.router)
    return app


app = create_app()
