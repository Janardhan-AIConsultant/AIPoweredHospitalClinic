"""Schemas for authentication and the admin / doctor dashboards. Phone numbers are always masked."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: UserRole
    doctor_id: uuid.UUID | None = None
    is_active: bool = True


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=200)
    role: UserRole
    doctor_id: uuid.UUID | None = None


class UserPatch(BaseModel):
    is_active: bool


class StaffAppointmentOut(BaseModel):
    appointment_reference: str
    patient_name: str
    patient_phone_masked: str
    doctor_id: uuid.UUID
    doctor_name: str
    appointment_date: date
    start_time: time
    end_time: time
    status: str
    reason_for_visit: str | None = None
    consultation_fee: Decimal
    notification_consent: bool


class AppointmentPage(BaseModel):
    items: list[StaffAppointmentOut]
    total: int
    limit: int
    offset: int


class StatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(COMPLETED|NO_SHOW)$")


class CancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class DoctorPatch(BaseModel):
    consultation_fee: Decimal | None = Field(default=None, ge=0, le=100000)
    bio: str | None = Field(default=None, max_length=2000)
    qualifications: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class AdminDoctorOut(BaseModel):
    id: uuid.UUID
    full_name: str
    specialization: str
    consultation_fee: Decimal
    is_active: bool
    upcoming_appointments: int


class LeaveRequest(BaseModel):
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=255)


class LeaveOut(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str | None = None
    affected_appointments: int = 0


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    actor_user_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity_type: str
    entity_id: str | None
    details: dict[str, Any] | None


class StatsOut(BaseModel):
    today: date
    today_total: int
    today_by_status: dict[str, int]
    upcoming_active: int
    active_doctors: int
    notifications: dict[str, int]
