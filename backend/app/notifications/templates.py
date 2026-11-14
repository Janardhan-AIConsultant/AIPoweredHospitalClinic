"""Approved-template catalogue. Template names must match those approved in Meta Business Manager.

Only minimal, non-medical variables are ever sent (no diagnosis, no reason for visit).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    name: str
    params: tuple[str, ...]  # body variables in positional order ({{1}}, {{2}}, ...)


CONFIRMATION = "appointment_confirmation"
CANCELLED = "appointment_cancelled"
RESCHEDULED = "appointment_rescheduled"
REMINDER = "appointment_reminder"
OTP = "otp_verification"

_COMMON = ("patient_name", "doctor_name", "date", "time", "reference")

TEMPLATES: dict[str, Template] = {
    name: Template(name, _COMMON) for name in (CONFIRMATION, CANCELLED, RESCHEDULED, REMINDER)
}
TEMPLATES[OTP] = Template(OTP, ("code",))  # sent directly, never via the outbox, so the code is not persisted

# Events whose message is pointless once the appointment is no longer active.
REQUIRES_ACTIVE = frozenset({CONFIRMATION, RESCHEDULED, REMINDER})


def body_parameters(template: str, payload: dict[str, str]) -> list[str]:
    spec = TEMPLATES[template]  # KeyError for unknown templates is deliberate: a permanent failure
    return [str(payload[p]) for p in spec.params]
