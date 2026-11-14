"""Housekeeping for short-lived data, run by the cron endpoint.

Retention (kept deliberately short; audit logs and appointments are never purged here):
- OTP challenges: 1 day after creation.
- Refresh tokens: 7 days after expiry, or 30 days after revocation (kept that long so replay of a
  rotated token is still recognised as theft).
- Finished outbox rows (SENT / SKIPPED / DEAD) and their delivery logs: 90 days.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationOutbox, OtpChallenge, RefreshToken
from app.models.enums import OutboxStatus

OTP_KEEP = timedelta(days=1)
REFRESH_EXPIRED_KEEP = timedelta(days=7)
REFRESH_REVOKED_KEEP = timedelta(days=30)
OUTBOX_KEEP = timedelta(days=90)
FINISHED = (OutboxStatus.SENT, OutboxStatus.SKIPPED, OutboxStatus.DEAD)


async def purge_expired(session: AsyncSession, now: datetime) -> dict[str, int]:
    otp = await session.execute(delete(OtpChallenge).where(OtpChallenge.created_at < now - OTP_KEEP))
    tokens = await session.execute(
        delete(RefreshToken).where(
            or_(
                RefreshToken.expires_at < now - REFRESH_EXPIRED_KEEP,
                RefreshToken.revoked_at < now - REFRESH_REVOKED_KEEP,
            )
        )
    )
    outbox = await session.execute(
        delete(NotificationOutbox).where(
            NotificationOutbox.status.in_(FINISHED), NotificationOutbox.updated_at < now - OUTBOX_KEEP
        )
    )
    await session.commit()
    return {
        "otp_challenges": otp.rowcount or 0,  # type: ignore[attr-defined]
        "refresh_tokens": tokens.rowcount or 0,  # type: ignore[attr-defined]
        "outbox": outbox.rowcount or 0,  # type: ignore[attr-defined]
    }
