"""Transactional outbox writers.

``enqueue_for_appointment`` only *adds* a row to the caller's session, so the message exists
if and only if the business change commits. ``dedupe_key`` makes every enqueue idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, NotificationOutbox
from app.models.enums import ACTIVE_STATUSES, RecipientRole
from app.notifications import templates
from app.utils.timezone import to_clinic

REMINDER_LEAD = timedelta(hours=24)


def _payload(appt: Appointment) -> dict[str, str]:
    local = to_clinic(appt.start_at)
    return {
        "patient_name": appt.patient_name.split()[0] if appt.patient_name.strip() else "there",
        "doctor_name": appt.doctor.full_name,
        "date": local.strftime("%d %b %Y"),
        "time": local.strftime("%I:%M %p").lstrip("0"),
        "reference": appt.appointment_reference,
    }


def _values(appt: Appointment, template: str, dedupe_key: str, now: datetime) -> dict[str, object]:
    return {
        "appointment_id": appt.id,
        "event_type": template,
        "recipient_role": RecipientRole.PATIENT.value,
        "recipient_phone_encrypted": appt.patient_phone_encrypted,  # already encrypted at rest
        "template_name": template,
        "payload": _payload(appt),
        "dedupe_key": dedupe_key,
        "next_attempt_at": now,
        "status": "PENDING",
        "attempts": 0,
        "max_attempts": 6,
    }


async def enqueue_for_appointment(session: AsyncSession, appt: Appointment, template: str, now: datetime) -> bool:
    """Queue a patient message in the current transaction. Returns False when the patient has not consented."""
    if not appt.notification_consent:
        return False
    stmt = (
        pg_insert(NotificationOutbox)
        .values(**_values(appt, template, f"{template}:{appt.id}", now))
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    await session.execute(stmt)
    return True


async def enqueue_due_reminders(session: AsyncSession, now: datetime) -> int:
    """Queue reminders for confirmed, consented appointments starting within the next 24 hours."""
    rows = (
        await session.scalars(
            select(Appointment).where(
                Appointment.appointment_status.in_(ACTIVE_STATUSES),
                Appointment.notification_consent.is_(True),
                Appointment.start_at > now,
                Appointment.start_at <= now + REMINDER_LEAD,
            )
        )
    ).all()
    queued = 0
    for appt in rows:
        result = await session.execute(
            pg_insert(NotificationOutbox)
            .values(**_values(appt, templates.REMINDER, f"{templates.REMINDER}:{appt.id}", now))
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        queued += result.rowcount or 0  # type: ignore[attr-defined]
    await session.commit()
    return queued
