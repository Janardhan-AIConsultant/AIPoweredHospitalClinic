"""Domain enumerations stored as constrained strings (portable, migration-friendly)."""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"


class SessionType(StrEnum):
    MORNING = "MORNING"
    EVENING = "EVENING"


class AppointmentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    RESCHEDULED = "RESCHEDULED"
    NO_SHOW = "NO_SHOW"


# Statuses that occupy a slot (used by the exclusion constraint and availability engine).
ACTIVE_STATUSES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"  # temporary failure, will retry
    DEAD = "DEAD"  # permanent failure / retries exhausted
    SKIPPED = "SKIPPED"  # e.g. no consent


class RecipientRole(StrEnum):
    PATIENT = "PATIENT"
    DOCTOR = "DOCTOR"
