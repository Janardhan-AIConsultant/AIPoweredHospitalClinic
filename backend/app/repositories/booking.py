"""Persistence for availability and booking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Integer, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, ClinicSetting, Doctor, DoctorLeave
from app.models.enums import ACTIVE_STATUSES
from app.utils.reference import format_reference


@dataclass(frozen=True)
class BookingPolicy:
    horizon_days: int = 30
    min_lead_minutes: int = 60


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_policy(self) -> BookingPolicy:
        rows = await self.session.execute(
            select(ClinicSetting.key, ClinicSetting.value).where(
                ClinicSetting.key.in_(("booking_horizon_days", "min_lead_minutes"))
            )
        )
        values = {k: v for k, v in rows.all()}
        defaults = BookingPolicy()
        return BookingPolicy(
            horizon_days=int(values.get("booking_horizon_days", defaults.horizon_days)),
            min_lead_minutes=int(values.get("min_lead_minutes", defaults.min_lead_minutes)),
        )

    def _doctor_stmt(self, doctor_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active.is_(True), Doctor.deleted_at.is_(None))

    async def get_doctor(self, doctor_id: uuid.UUID) -> Doctor | None:
        return (await self.session.scalars(self._doctor_stmt(doctor_id))).unique().one_or_none()

    async def lock_doctor(self, doctor_id: uuid.UUID) -> Doctor | None:
        """``SELECT ... FOR UPDATE`` on the doctor row only (``of=Doctor`` keeps the joined
        specialization row unlocked). Serialises concurrent bookings for one doctor so
        losers get a clean 'slot unavailable' instead of a deadlock."""
        stmt = self._doctor_stmt(doctor_id).with_for_update(of=Doctor).execution_options(populate_existing=True)
        return (await self.session.scalars(stmt)).unique().one_or_none()

    async def next_reference(self, day: date) -> str:
        """Allocate ``YYYYMMDD-NNNN``: one more than the highest counter already used for that date.

        A transaction-scoped advisory lock keyed on the date serialises allocation, so two patients booking
        the same date at the same moment (even with different doctors) never get the same number. The lock is
        released automatically at commit or rollback; the unique constraint remains the final safety net.
        """
        key = 7_000_000_000 + int(f"{day:%Y%m%d}")  # one lock per appointment date
        await self.session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        ref = Appointment.appointment_reference
        last = await self.session.scalar(
            select(func.max(cast(func.substr(ref, 10), Integer))).where(ref.op("~")(f"^{day:%Y%m%d}-[0-9]+$"))
        )
        return format_reference(day, (last or 0) + 1)

    async def on_leave(self, doctor_id: uuid.UUID, day: date) -> bool:
        stmt = select(DoctorLeave.id).where(
            DoctorLeave.doctor_id == doctor_id, DoctorLeave.start_date <= day, DoctorLeave.end_date >= day
        )
        return await self.session.scalar(stmt.limit(1)) is not None

    async def active_intervals(self, doctor_id: uuid.UUID, day: date) -> list[tuple[datetime, datetime]]:
        stmt = select(Appointment.start_at, Appointment.end_at).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == day,
            Appointment.appointment_status.in_(ACTIVE_STATUSES),
            Appointment.deleted_at.is_(None),
        )
        return [(s, e) for s, e in (await self.session.execute(stmt)).all()]

    async def get_by_idempotency_key(self, key: str) -> Appointment | None:
        return await self.session.scalar(select(Appointment).where(Appointment.idempotency_key == key))

    async def get_by_reference(self, reference: str) -> Appointment | None:
        return await self.session.scalar(select(Appointment).where(Appointment.appointment_reference == reference))

    def add(self, appointment: Appointment) -> None:
        self.session.add(appointment)
