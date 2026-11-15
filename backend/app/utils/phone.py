"""E.164 phone validation and normalisation (default region: India)."""

from __future__ import annotations

import re

E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str, default_country_code: str = "+91") -> str:
    """Return an E.164 number or raise ValueError.

    Accepts ``9876543210``, ``09876543210``, ``+91 98765 43210``.
    """
    cleaned = re.sub(r"[\s\-()]", "", raw or "")
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        cleaned = default_country_code + cleaned.lstrip("0")
    if not E164_RE.match(cleaned):
        raise ValueError("Invalid phone number; expected E.164 format")
    if cleaned.startswith("+91") and not re.match(r"^\+91[6-9]\d{9}$", cleaned):
        raise ValueError("Invalid Indian mobile number")
    return cleaned
