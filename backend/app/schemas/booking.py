"""Booking request/response schemas. Responses never include phone or email."""

from __future__ import annotations

import re
import uuid
from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SlotOut(BaseModel):
    start_time: time
    end_time: time


class SlotsResponse(BaseModel):
    doctor_id: uuid.UUID
    date: date
    slots: list[SlotOut]


class BookingRequest(BaseModel):
    doctor_id: uuid.UUID
    date: date
    start_time: time
    patient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=254)
    reason_for_visit: str | None = Field(default=None, max_length=300)
    notification_consent: bool = False

    @field_validator("patient_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Name is too short")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("Invalid email address")
        return v.strip()

    @field_validator("start_time")
    @classmethod
    def _seconds(cls, v: time) -> time:
        return v.replace(second=0, microsecond=0)


class AppointmentOut(BaseModel):
    appointment_reference: str
    doctor_id: uuid.UUID
    doctor_name: str
    specialization: str
    appointment_date: date
    start_time: time
    end_time: time
    consultation_fee: Decimal
    status: str
    patient_name: str
    reason_for_visit: str | None = None
