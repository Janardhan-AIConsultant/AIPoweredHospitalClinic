"""specializations, doctors, doctor_schedules, doctor_leave."""

from __future__ import annotations

import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.enums import SessionType


class Specialization(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "specializations"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)


class Doctor(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "doctors"

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("specializations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    qualifications: Mapped[str | None] = mapped_column(String(255))
    experience_years: Mapped[int] = mapped_column(Integer, nullable=False)
    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    whatsapp_encrypted: Mapped[str | None] = mapped_column(String(512))
    slot_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default="30", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    specialization: Mapped[Specialization] = relationship(lazy="joined")
    schedules: Mapped[list[DoctorSchedule]] = relationship(back_populates="doctor", lazy="selectin")

    __table_args__ = (
        CheckConstraint("experience_years >= 0", name="experience_nonneg"),
        CheckConstraint("consultation_fee >= 0", name="fee_nonneg"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 120", name="slot_minutes_range"),
    )


class DoctorSchedule(UUIDPkMixin, TimestampMixin, Base):
    """One working session (morning/evening) on one weekday. weekday: Monday=0 .. Sunday=6."""

    __tablename__ = "doctor_schedules"

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    session_type: Mapped[SessionType] = mapped_column(
        Enum(SessionType, native_enum=False, length=16, create_constraint=True, name="session_type"), nullable=False
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    break_start: Mapped[time | None] = mapped_column(Time)
    break_end: Mapped[time | None] = mapped_column(Time)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)

    doctor: Mapped[Doctor] = relationship(back_populates="schedules")

    __table_args__ = (
        UniqueConstraint("doctor_id", "weekday", "session_type", name="uq_schedule_doctor_day_session"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
        CheckConstraint(
            "(break_start IS NULL AND break_end IS NULL) OR "
            "(break_start IS NOT NULL AND break_end IS NOT NULL AND break_end > break_start "
            "AND break_start >= start_time AND break_end <= end_time)",
            name="break_valid",
        ),
    )


class DoctorLeave(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "doctor_leave"

    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    __table_args__ = (CheckConstraint("end_date >= start_date", name="date_order"),)
