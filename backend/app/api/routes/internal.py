"""Cron-triggered internal endpoints (Vercel Cron or GitHub Actions). Protected by ``CRON_SECRET``."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.booking import get_cipher, get_clock
from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, ExternalServiceError
from app.core.security import FieldCipher
from app.database.session import get_sessionmaker
from app.notifications.dispatcher import drain
from app.notifications.outbox import enqueue_due_reminders
from app.notifications.whatsapp import WhatsAppSender, build_sender
from app.services.retention import purge_expired

router = APIRouter(prefix="/internal", tags=["internal"])


def require_cron_secret(
    authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> None:
    secret = settings.cron_secret.get_secret_value()
    if not secret:
        raise ExternalServiceError("Cron endpoint is not configured.")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, secret):
        raise AuthenticationError("Invalid cron credentials.")


def get_sender(settings: Settings = Depends(get_settings)) -> WhatsAppSender:
    return build_sender(settings)


def get_maker() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


@router.api_route("/cron/notifications", methods=["GET", "POST"], dependencies=[Depends(require_cron_secret)])
async def run_notifications(
    maker: async_sessionmaker[AsyncSession] = Depends(get_maker),
    sender: WhatsAppSender = Depends(get_sender),
    cipher: FieldCipher = Depends(get_cipher),
    clock: Callable[[], datetime] = Depends(get_clock),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Queue due reminders, then drain the outbox. Vercel Cron issues GET; Actions may POST."""
    async with maker() as session:
        purged = await purge_expired(session, clock())
    if settings.whatsapp_mode == "mock" and settings.app_env in ("production", "staging"):
        # The mock sender would mark real patients' messages SENT without sending anything.
        return {"skipped": "whatsapp_not_configured", "reminders_queued": 0, "claimed": 0, "purged": purged}
    async with maker() as session:
        reminders = await enqueue_due_reminders(session, clock())
    result = await drain(maker, sender, cipher, clock=clock)
    return {"reminders_queued": reminders, **asdict(result), "purged": purged}
