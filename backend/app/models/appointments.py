"""appointments, with DB-level double-booking protection."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPkMixin
from app.models.doctors import Doctor
from app.models.enums import AppointmentStatus


class Appointment(UUIDPkMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "appointments"

    appointment_reference: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), index=True
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False
    )
    patient_name: Mapped[str] = mapped_column(String(120), nullable=False)
    patient_phone_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    patient_phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_for_visit: Mapped[str | None] = mapped_column(String(300))

    # Clinic-local presentation fields + UTC instants used by the exclusion constraint.
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consultation_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    appointment_status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=16, create_constraint=True, name="appointment_status"),
        nullable=False,
        default=AppointmentStatus.CONFIRMED,
    )
    notification_consent: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    rescheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("appointments.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    doctor: Mapped[Doctor] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("end_at > start_at", name="time_order"),
        CheckConstraint("consultation_fee >= 0", name="fee_nonneg"),
        # No two PENDING/CONFIRMED appointments for one doctor may overlap (requires btree_gist).
        ExcludeConstraint(
            ("doctor_id", "="),
            (func.tstzrange(text("start_at"), text("end_at"), text("'[)'")), "&&"),
            where=text("appointment_status IN ('PENDING','CONFIRMED') AND deleted_at IS NULL"),
            using="gist",
            name="ex_appointments_no_overlap",
        ),
        Index("ix_appointments_doctor_date", "doctor_id", "appointment_date"),
        Index("ix_appointments_status_start", "appointment_status", "start_at"),
    )
