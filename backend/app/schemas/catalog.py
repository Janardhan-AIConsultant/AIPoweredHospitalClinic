"""Public response schemas. Deliberately omit doctor WhatsApp and internal flags."""

from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class SpecializationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    weekday: int
    session_type: str
    start_time: time
    end_time: time
    break_start: time | None = None
    break_end: time | None = None


class DoctorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str
    qualifications: str | None = None
    experience_years: int
    consultation_fee: Decimal
    bio: str | None = None
    photo_url: str | None = None
    specialization: SpecializationOut
    schedules: list[ScheduleOut]
