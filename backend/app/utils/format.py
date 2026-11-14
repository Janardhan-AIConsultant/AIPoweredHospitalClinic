"""Small formatting helpers."""

from __future__ import annotations

from datetime import time


def hhmm(t: time) -> str:
    return t.strftime("%H:%M")
