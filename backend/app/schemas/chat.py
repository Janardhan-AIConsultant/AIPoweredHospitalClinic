from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.ai.guardrails import MAX_HISTORY_MESSAGES, MAX_MESSAGE_CHARS, MAX_TOTAL_CHARS
from app.schemas.booking import _EMAIL_RE


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]  # clients can never inject system/tool messages
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=MAX_HISTORY_MESSAGES * 2)

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
