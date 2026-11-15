"""Outbox drain worker: claim rows, send, record the attempt, schedule retries.

Safe to run concurrently (``FOR UPDATE SKIP LOCKED``) and to run again after a crash (rows stuck in
PROCESSING are reclaimed after ``STALE_AFTER``). Delivery is at-least-once.
"""

from __future__ import annotations

import logging
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import FieldCipher
from app.models import Appointment, NotificationLog, NotificationOutbox
from app.models.enums import ACTIVE_STATUSES, OutboxStatus
from app.notifications import templates
from app.notifications.whatsapp import SendError, WhatsAppSender
from app.utils.timezone import utcnow

logger = logging.getLogger(__name__)

BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6))
STALE_AFTER = timedelta(minutes=5)


def backoff_for(attempt: int) -> timedelta:
    return BACKOFF[min(attempt, len(BACKOFF)) - 1]


@dataclass
class DrainResult:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    dead: int = 0
    skipped: int = 0


async def _claim(session: AsyncSession, now: datetime, limit: int) -> list[NotificationOutbox]:
    rows = (
        await session.scalars(
            select(NotificationOutbox)
            .where(
                or_(
                    (NotificationOutbox.status.in_([OutboxStatus.PENDING, OutboxStatus.FAILED]))
                    & (NotificationOutbox.next_attempt_at <= now),
                    (NotificationOutbox.status == OutboxStatus.PROCESSING)
                    & (NotificationOutbox.locked_at < now - STALE_AFTER),
                )
            )
            .order_by(NotificationOutbox.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        row.status = OutboxStatus.PROCESSING
        row.locked_at = now
    await session.commit()
    return list(rows)


async def drain(
    maker: async_sessionmaker[AsyncSession],
    sender: WhatsAppSender,
    cipher: FieldCipher,
    *,
    clock: Callable[[], datetime] = utcnow,
    batch_size: int = 20,
    budget_seconds: float = 20.0,
) -> DrainResult:
    """Process up to ``batch_size`` due messages within ``budget_seconds`` (serverless-friendly)."""
    result = DrainResult()
    started = _time.monotonic()
    async with maker() as session:
        claimed = await _claim(session, clock(), batch_size)
    result.claimed = len(claimed)
    for row in claimed:
        if _time.monotonic() - started > budget_seconds:
            await _release(maker, row.id, clock())  # put it back untouched for the next run
            continue
        await _process(maker, row.id, sender, cipher, clock, result)
    return result


async def _release(maker: async_sessionmaker[AsyncSession], outbox_id: object, now: datetime) -> None:
    async with maker() as s:
        row = await s.get(NotificationOutbox, outbox_id)
        if row is not None and row.status == OutboxStatus.PROCESSING:
            row.status, row.locked_at, row.next_attempt_at = OutboxStatus.PENDING, None, now
            await s.commit()


async def _process(
    maker: async_sessionmaker[AsyncSession],
    outbox_id: object,
    sender: WhatsAppSender,
    cipher: FieldCipher,
    clock: Callable[[], datetime],
    result: DrainResult,
) -> None:
    async with maker() as s:
        row = await s.get(NotificationOutbox, outbox_id)
        if row is None or row.status != OutboxStatus.PROCESSING:
            return
        appt = await s.get(Appointment, row.appointment_id) if row.appointment_id else None
        skip = (
            appt is None
            or not appt.notification_consent
            or (row.template_name in templates.REQUIRES_ACTIVE and appt.appointment_status not in ACTIVE_STATUSES)
        )
        if skip:
            row.status, row.locked_at = OutboxStatus.SKIPPED, None
            await s.commit()
            result.skipped += 1
            return

        attempt = row.attempts + 1
        provider_id: str | None = None
        error: SendError | None = None
        try:
            phone = cipher.decrypt(row.recipient_phone_encrypted)
            params = templates.body_parameters(row.template_name, row.payload)
            provider_id = await sender.send_template(phone, row.template_name, params)
        except SendError as exc:
            error = exc
        except Exception as exc:  # noqa: BLE001 - e.g. unknown template / undecryptable phone: never retry
            error = SendError("Message could not be prepared.", permanent=True, code=type(exc).__name__)

        row.attempts, row.locked_at = attempt, None
        if error is None:
            row.status, row.last_error = OutboxStatus.SENT, None
            result.sent += 1
            s.add(NotificationLog(outbox_id=row.id, attempt_no=attempt, provider_message_id=provider_id, status="sent"))
        else:
            row.last_error = f"{error.code}: {error}"[:500]
            if error.permanent or attempt >= row.max_attempts:
                row.status = OutboxStatus.DEAD
                result.dead += 1
            else:
                row.status = OutboxStatus.FAILED
                row.next_attempt_at = clock() + backoff_for(attempt)
                result.retried += 1
            s.add(
                NotificationLog(
                    outbox_id=row.id,
                    attempt_no=attempt,
                    status="failed",
                    http_status=error.http_status,
                    error_code=error.code[:64],
                    error_message=str(error)[:500],
                )
            )
            logger.warning(
                "notification_failed",
                extra={"operation": "outbox.drain", "error_category": error.code, "attempt": attempt},
            )
        await s.commit()
