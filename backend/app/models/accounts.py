"""users and patients."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.enums import UserRole


class User(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Staff (admin/doctor) and optional patient accounts."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, length=16, create_constraint=True, name="user_role"), nullable=False
    )
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="SET NULL"), unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_users_email_lower", func.lower(email), unique=True, postgresql_where="deleted_at IS NULL"),
    )


class Patient(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Patient profile. Phone/email are encrypted at rest; ``phone_hash`` (HMAC) allows lookup."""

    __tablename__ = "patients"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    email_encrypted: Mapped[str | None] = mapped_column(String(512))
    notification_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    notification_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_patients_phone_hash_active", "phone_hash", unique=True, postgresql_where="deleted_at IS NULL"),
    )
