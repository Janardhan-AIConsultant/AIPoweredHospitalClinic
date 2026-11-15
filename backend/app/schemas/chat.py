from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.ai.guardrails import MAX_HISTORY_MESSAGES, MAX_MESSAGE_CHARS, MAX_TOTAL_CHARS
from app.schemas.booking import _EMAIL_RE


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]  # clients can never inject system/tool messages
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


HHMMStr = Annotated[str, StringConstraints(pattern=r"^\d{2}:\d{2}$")]


class SlotTime(BaseModel):
    time: HHMMStr
    label: str = Field(max_length=12)


class SlotsOffer(BaseModel):
    """The open times the patient was last shown. Strictly typed because the client sends it back:
    it only tells the assistant which doctor/date a bare "10:00 AM" refers to, and every booking is
    still re-checked against real availability."""

    doctor_id: uuid.UUID
    doctor_name: str = Field(max_length=120)
    date: date
    date_label: str = Field(max_length=32)
    times: list[SlotTime] = Field(max_length=40)


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=MAX_HISTORY_MESSAGES * 2)
    context: SlotsOffer | None = None

    @field_validator("messages")
    @classmethod
    def _shape(cls, v: list[ChatMessageIn]) -> list[ChatMessageIn]:
        if v[-1].role != "user":
            raise ValueError("The last message must come from the user")
        if sum(len(m.content) for m in v) > MAX_TOTAL_CHARS:
            raise ValueError("Conversation is too long")
        if not v[-1].content.strip():
            raise ValueError("Empty message")
        return v


class ProposalSummary(BaseModel):
    doctor_name: str
    specialization: str
    date: str
    start_time: str
    fee: str


class Proposal(BaseModel):
    token: str
    summary: ProposalSummary


class ChatResponse(BaseModel):
    reply: str
    guard: str = "none"
    proposal: Proposal | None = None
    slots: SlotsOffer | None = None  # replace the client's offered slots with these
    clear_slots: bool = False  # the date just checked had none: drop any old offer


class ConfirmRequest(BaseModel):
    proposal_token: str = Field(min_length=20, max_length=2000)
    patient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=6, max_length=20)
    email: str | None = Field(default=None, max_length=254)
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
        if not v:
            return None
        if not _EMAIL_RE.match(v.strip()):
            raise ValueError("Invalid email address")
        return v.strip()
