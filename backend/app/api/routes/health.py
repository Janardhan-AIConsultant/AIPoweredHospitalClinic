"""Liveness and readiness endpoints. Readiness reports dependency modes, never secrets."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.core.config import Settings, get_settings
from app.database.session import get_sessionmaker

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


async def _database_status(settings: Settings) -> str:
    if not settings.database_url.get_secret_value():
        return "not_configured"
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - never leak driver errors or URLs
        logger.warning("db_probe_failed", extra={"operation": "readiness"})
        return "unavailable"


@router.get("/health/ready")
async def readiness(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    db = await _database_status(settings)
    return {
        "status": "degraded" if db == "unavailable" else "ok",
        "environment": settings.app_env,
        "database": db,
        "integrations": {
            "llm": settings.llm_mode,
            "chroma": settings.chroma_mode,
            "whatsapp": settings.whatsapp_mode,
        },
    }
