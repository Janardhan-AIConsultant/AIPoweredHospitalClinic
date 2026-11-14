"""Timezone helpers: store UTC, display in the clinic timezone."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def clinic_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().clinic_timezone)


def utcnow() -> datetime:
    return datetime.now(UTC)


def clinic_now() -> datetime:
    return utcnow().astimezone(clinic_tz())


def to_utc(local_date: date, local_time: time) -> datetime:
    """Combine a clinic-local date and time into an aware UTC datetime."""
    return datetime.combine(local_date, local_time, tzinfo=clinic_tz()).astimezone(UTC)


def to_clinic(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed")
    return dt.astimezone(clinic_tz())
