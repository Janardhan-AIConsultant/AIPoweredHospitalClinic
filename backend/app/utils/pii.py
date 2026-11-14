"""PII masking helpers used by logging and audit code."""

from __future__ import annotations

import re
from typing import Any

_PHONE_RE = re.compile(r"(?<!\d)(\+?\d[\d\s\-]{7,}\d)(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_SECRET_KEYS = {"password", "token", "secret", "authorization", "api_key", "otp", "access_token"}


def mask_phone(phone: str) -> str:
    """Keep only the country prefix and last 2 digits: +91******10."""
    digits = re.sub(r"[^\d+]", "", phone)
    if len(digits) <= 4:
        return "*" * len(digits)
    return digits[:3] + "*" * (len(digits) - 5) + digits[-2:]


def mask_text(text: str) -> str:
    """Mask phone numbers and e-mail addresses inside free text."""
    text = _PHONE_RE.sub(lambda m: mask_phone(m.group(1)), text)
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively mask secrets and PII in a dict destined for logs."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SECRET_KEYS:
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = redact_mapping(value)
        elif isinstance(value, str):
            out[key] = mask_text(value)
        else:
            out[key] = value
    return out
