"""notification_outbox and notification_logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UUIDPkMixin
from app.models.enums import OutboxStatus, RecipientRole


class NotificationOutbox(UUIDPkMixin, TimestampMixin, Base):
    """Written in the same transaction as the business change (transactional outbox)."""

    __tablename__ = "notification_outbox"

    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient_role: Mapped[RecipientRole] = mapped_column(
        Enum(RecipientRole, native_enum=False, length=16, create_constraint=True, name="recipient_role"),
        nullable=False,
    )
    recipient_phone_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    template_name: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)  # minimal, no medical data
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=16, create_constraint=True, name="outbox_status"),
        nullable=False,
        default=OutboxStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6, server_default="6", nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    __table_args__ = (Index("ix_outbox_status_next", "status", "next_attempt_at"),)


class NotificationLog(UUIDPkMixin, Base):
    __tablename__ = "notification_logs"

    outbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)  # sent|delivered|read|failed
    http_status: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)  # sanitised, no PII
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
