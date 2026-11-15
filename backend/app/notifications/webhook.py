"""WhatsApp webhook helpers: signature verification, delivery statuses and STOP opt-out."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import FieldCipher
from app.models import Appointment, NotificationLog, Patient
from app.utils.phone import normalize_phone
from app.utils.timezone import utcnow

logger = logging.getLogger(__name__)

STATUSES = {"sent", "delivered", "read", "failed"}
OPT_OUT_WORDS = {"stop", "unsubscribe", "stop all"}


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Check Meta's ``X-Hub-Signature-256: sha256=<hex>`` over the raw body (constant time)."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _values(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if isinstance(change.get("value"), dict):
                out.append(change["value"])
    return out


async def process_payload(session: AsyncSession, cipher: FieldCipher, payload: dict[str, Any]) -> dict[str, int]:
    counts = {"statuses": 0, "opt_outs": 0}
    for value in _values(payload):
        for st in value.get("statuses") or []:
            if await _record_status(session, st):
                counts["statuses"] += 1
        for msg in value.get("messages") or []:
            if await _handle_message(session, cipher, msg):
                counts["opt_outs"] += 1
    await session.commit()
    return counts


async def _record_status(session: AsyncSession, st: dict[str, Any]) -> bool:
    message_id, status = st.get("id"), st.get("status")
    if not isinstance(message_id, str) or status not in STATUSES:
        return False
    logs = (
        await session.scalars(select(NotificationLog).where(NotificationLog.provider_message_id == message_id))
    ).all()
    if not logs or any(entry.status == status for entry in logs):
        return False  # unknown message, or duplicate delivery of the same event
    errors = st.get("errors") or [{}]
    first = errors[0] if isinstance(errors[0], dict) else {}
    session.add(
        NotificationLog(
            outbox_id=logs[0].outbox_id,
            attempt_no=logs[0].attempt_no,
            provider_message_id=message_id,
            status=status,
            error_code=str(first.get("code"))[:64] if first.get("code") is not None else None,
        )
    )
    return True


async def _handle_message(session: AsyncSession, cipher: FieldCipher, msg: dict[str, Any]) -> bool:
    text = ((msg.get("text") or {}).get("body") or "").strip().lower()
    if msg.get("type") != "text" or text not in OPT_OUT_WORDS:
        return False
    try:
        phone_hash = cipher.hash_phone(normalize_phone("+" + str(msg.get("from", "")).lstrip("+")))
    except ValueError:
        return False
    await session.execute(
        update(Patient)
        .where(Patient.phone_hash == phone_hash)
        .values(notification_consent=False, notification_consent_at=None)
    )
    await session.execute(
        update(Appointment)
        .where(Appointment.patient_phone_hash == phone_hash, Appointment.start_at > utcnow())
        .values(notification_consent=False)
    )
    logger.info("whatsapp_opt_out", extra={"operation": "webhook"})
    return True
