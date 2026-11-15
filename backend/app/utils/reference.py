"""Appointment reference format: ``<appointment date>-<counter>``, e.g. ``20261212-0001``.

The counter is per appointment date, starts at 0001 and grows by one for every appointment booked for
that date (cancelled ones keep their number, so a reference is never reused). It is allocated by
``BookingRepository.next_reference``; this module only knows the format.
"""

from __future__ import annotations

import re
from datetime import date

REFERENCE_COLUMN_LENGTH = 16  # appointment_reference is String(16)
COUNTER_WIDTH = 4  # 0001 ... 9999; a busier day simply grows to 5 digits (still fits the column)
_REFERENCE_RE = re.compile(r"^(\d{8})-(\d+)$")


def format_reference(day: date, counter: int) -> str:
    if counter < 1:
        raise ValueError("The counter starts at 1")
    return f"{day:%Y%m%d}-{counter:0{COUNTER_WIDTH}d}"


def parse_reference(reference: str) -> tuple[str, int] | None:
    """(YYYYMMDD, counter) for a reference in the date-counter format, else None (older random references)."""
    m = _REFERENCE_RE.match(reference)
    return (m.group(1), int(m.group(2))) if m else None
