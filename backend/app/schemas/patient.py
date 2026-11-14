"""Patient self-service schemas."""

from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field


class OtpRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=20)


class OtpVerify(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    code: str = Field(pattern=r"^\d{6}$")


class OtpRequested(BaseModel):
    message: str = "If this number has appointments, a verification code was sent on WhatsApp."


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    expires_in: int


class RescheduleRequest(BaseModel):
    date: date
    start_time: time


class CancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
