"""Small formatting helpers."""

from __future__ import annotations

from datetime import date, time


def hhmm(t: time) -> str:
    return t.strftime("%H:%M")


def time12(t: time) -> str:
    """10:30 AM / 4:00 PM (no leading zero)."""
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def date_label(d: date) -> str:
    """Sat, 12 Dec 2026. Computed here, never by the language model, which gets weekdays wrong."""
    return f"{d:%a}, {d.day} {d:%b %Y}"
