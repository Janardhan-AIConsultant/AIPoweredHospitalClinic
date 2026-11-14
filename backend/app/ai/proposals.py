"""Signed, short-lived booking proposals.

The model can only *propose* a booking. The proposal is an HMAC-signed token that the
UI hands back, together with the patient's details, to ``POST /chat/confirm``. The
LLM never sees the token or the patient's personal details, and it cannot execute a
booking on its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import jwt

from app.core.config import Settings
from app.core.exceptions import ValidationFailure

PROPOSAL_TTL = timedelta(minutes=10)
_TYP = "booking_proposal"


def create_proposal(
    settings: Settings, doctor_id: uuid.UUID, day: date, start: time, now: datetime | None = None
) -> str:
    issued = now or datetime.now(UTC)
    claims: dict[str, Any] = {
        "typ": _TYP,
        "doctor_id": str(doctor_id),
        "date": day.isoformat(),
        "start_time": start.strftime("%H:%M"),
        "iat": issued,
        "exp": issued + PROPOSAL_TTL,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _secret(settings), algorithm="HS256")


def read_proposal(settings: Settings, token: str) -> dict[str, Any]:
    """Return verified claims with typed ``doctor_id``/``date``/``start_time`` plus ``jti``."""
    try:
        claims = jwt.decode(token, _secret(settings), algorithms=["HS256"], options={"require": ["exp", "jti"]})
        if claims.get("typ") != _TYP:
            raise jwt.InvalidTokenError("wrong token type")
        return {
            "doctor_id": uuid.UUID(claims["doctor_id"]),
            "date": date.fromisoformat(claims["date"]),
            "start_time": time.fromisoformat(claims["start_time"]),
            "jti": claims["jti"],
        }
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise ValidationFailure("This booking proposal is invalid or has expired. Please ask me again.") from exc


def _secret(settings: Settings) -> str:
    secret = settings.jwt_secret_key.get_secret_value()
    if len(secret) < 16:
        raise RuntimeError("JWT_SECRET_KEY must be configured to use chat booking")
    return secret
