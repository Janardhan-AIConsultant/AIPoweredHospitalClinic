"""Dashboard use-cases for admins and doctors.

Doctors are always scoped to their own doctor_id; "not yours" and "does not exist" both answer 404.
Each mutation is audited. Booking-level changes (cancel) commit inside ``BookingService`` and the
audit row is committed right after, so a crash in between can lose the audit row but never the change.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.core.principal import Principal
from app.core.security import FieldCipher
from app.models import Appointment, Doctor, DoctorLeave, NotificationOutbox
from app.models.enums import ACTIVE_STATUSES, AppointmentStatus, OutboxStatus, UserRole
from app.schemas.booking import AppointmentOut
from app.schemas.staff import (
    AdminDoctorOut,
    AppointmentPage,
    DoctorPatch,
    LeaveOut,
    StaffAppointmentOut,
    StatsOut,
)
from app.services import audit
from app.services.booking import BookingService
from app.utils.pii import mask_phone
from app.utils.timezone import to_clinic, utcnow

MAX_PAGE = 100


class StaffService:
    def __init__(
        self,
        session: AsyncSession,
        cipher: FieldCipher,
        booking: BookingService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session, self.cipher, self.booking, self.clock = session, cipher, booking, clock

    def today(self) -> date:
        return to_clinic(self.clock()).date()

    def _scope(self, who: Principal, doctor_id: uuid.UUID | None) -> uuid.UUID | None:
        if who.role == UserRole.DOCTOR:
            if who.doctor_id is None:
                raise NotFoundError("Doctor profile not found.")
            return who.doctor_id
        return doctor_id

    def _out(self, a: Appointment) -> StaffAppointmentOut:
        try:
            phone = mask_phone(self.cipher.decrypt(a.patient_phone_encrypted))
        except ValueError:
            phone = "unavailable"
        return StaffAppointmentOut(
            appointment_reference=a.appointment_reference,
            patient_name=a.patient_name,
            patient_phone_masked=phone,
            doctor_id=a.doctor_id,
            doctor_name=a.doctor.full_name,
            appointment_date=a.appointment_date,
            start_time=a.start_time,
            end_time=a.end_time,
            status=a.appointment_status.value,
            reason_for_visit=a.reason_for_visit,
            consultation_fee=a.consultation_fee,
            notification_consent=a.notification_consent,
        )

    # ---------------------------------------------------------- appointments
    async def list_appointments(
        self,
        who: Principal,
        *,
        date_from: date | None,
        date_to: date | None,
        doctor_id: uuid.UUID | None,
        status: AppointmentStatus | None,
        limit: int,
        offset: int,
    ) -> AppointmentPage:
        limit = max(1, min(limit, MAX_PAGE))
        conds: list[ColumnElement[bool]] = [Appointment.deleted_at.is_(None)]
        scoped = self._scope(who, doctor_id)
        if scoped:
            conds.append(Appointment.doctor_id == scoped)
        if date_from:
            conds.append(Appointment.appointment_date >= date_from)
        if date_to:
            conds.append(Appointment.appointment_date <= date_to)
        if status:
            conds.append(Appointment.appointment_status == status)
        total = await self.session.scalar(select(func.count()).select_from(Appointment).where(*conds)) or 0
        rows = await self.session.scalars(
            select(Appointment).where(*conds).order_by(Appointment.start_at).limit(limit).offset(max(0, offset))
        )
        return AppointmentPage(items=[self._out(a) for a in rows], total=total, limit=limit, offset=max(0, offset))

    async def _owned(self, who: Principal, reference: str) -> Appointment:
        appt = await self.booking.repo.get_by_reference(reference.strip().upper())
        if appt is None or (who.role == UserRole.DOCTOR and appt.doctor_id != who.doctor_id):
            raise NotFoundError("Appointment not found.")
        return appt

    async def set_status(self, who: Principal, reference: str, status: AppointmentStatus) -> StaffAppointmentOut:
        appt = await self._owned(who, reference)
        if appt.appointment_status not in ACTIVE_STATUSES:
            raise ConflictError("Only active appointments can be completed or marked no-show.")
        if appt.start_at > self.clock():
            raise ValidationFailure("This appointment has not started yet.")
        old = appt.appointment_status.value
        appt.appointment_status = status
        appt.version += 1
        audit.record(self.session, who, "appointment.status", "appointment", appt.id, {"from": old, "to": status.value})
        await self.session.commit()
        return self._out(appt)

    async def cancel(self, who: Principal, reference: str, reason: str | None) -> AppointmentOut:
        appt = await self._owned(who, reference)
        out = await self.booking.cancel(appt.appointment_reference, reason)
        audit.record(self.session, who, "appointment.cancel", "appointment", appt.id, {"by": who.role.value})
        await self.session.commit()
        return out

    # ---------------------------------------------------------------- doctors
    async def _upcoming(self, doctor_id: uuid.UUID) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.doctor_id == doctor_id,
                    Appointment.appointment_status.in_(ACTIVE_STATUSES),
                    Appointment.start_at > self.clock(),
                )
            )
            or 0
        )

    async def _doctor_out(self, d: Doctor) -> AdminDoctorOut:
        return AdminDoctorOut(
            id=d.id,
            full_name=d.full_name,
            specialization=d.specialization.name,
            consultation_fee=d.consultation_fee,
            is_active=d.is_active,
            upcoming_appointments=await self._upcoming(d.id),
        )

    async def list_doctors(self) -> list[AdminDoctorOut]:
        docs = await self.session.scalars(select(Doctor).where(Doctor.deleted_at.is_(None)).order_by(Doctor.full_name))
        return [await self._doctor_out(d) for d in docs]

    async def update_doctor(self, who: Principal, doctor_id: uuid.UUID, patch: DoctorPatch) -> AdminDoctorOut:
        doctor = await self.session.get(Doctor, doctor_id)
        if doctor is None or doctor.deleted_at is not None:
            raise NotFoundError("Doctor not found.")
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationFailure("Nothing to update.")
        for key, value in changes.items():
            if value is None and key in ("consultation_fee", "is_active"):
                raise ValidationFailure(f"{key} cannot be null.")
            setattr(doctor, key, value)
        audit.record(self.session, who, "doctor.update", "doctor", doctor.id, {"fields": sorted(changes)})
        await self.session.commit()
        return await self._doctor_out(doctor)

    # ------------------------------------------------------------------ leave
    async def add_leave(
        self, who: Principal, doctor_id: uuid.UUID | None, start: date, end: date, reason: str | None
    ) -> LeaveOut:
        target = self._scope(who, doctor_id)
        if target is None:
            raise ValidationFailure("doctor_id is required.")
        if end < start:
            raise ValidationFailure("End date must not be before start date.")
        if start < self.today():
            raise ValidationFailure("Leave cannot start in the past.")
        doctor = await self.session.get(Doctor, target)
        if doctor is None or doctor.deleted_at is not None:
            raise NotFoundError("Doctor not found.")
        affected = (
            await self.session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.doctor_id == target,
                    Appointment.appointment_status.in_(ACTIVE_STATUSES),
                    Appointment.appointment_date.between(start, end),
                )
            )
            or 0
        )
        leave = DoctorLeave(doctor_id=target, start_date=start, end_date=end, reason=reason, created_by=who.user_id)
        self.session.add(leave)
        await self.session.flush()
        audit.record(
            self.session,
            who,
            "leave.create",
            "doctor",
            target,
            {"start": str(start), "end": str(end), "affected": affected},
        )
        await self.session.commit()
        return LeaveOut(
            id=leave.id, doctor_id=target, start_date=start, end_date=end, reason=reason, affected_appointments=affected
        )

    async def list_leave(self, who: Principal, doctor_id: uuid.UUID | None) -> list[LeaveOut]:
        target = self._scope(who, doctor_id)
        stmt = select(DoctorLeave).where(DoctorLeave.end_date >= self.today()).order_by(DoctorLeave.start_date)
        if target:
            stmt = stmt.where(DoctorLeave.doctor_id == target)
        return [
            LeaveOut(id=r.id, doctor_id=r.doctor_id, start_date=r.start_date, end_date=r.end_date, reason=r.reason)
            for r in await self.session.scalars(stmt)
        ]

    async def delete_leave(self, who: Principal, leave_id: uuid.UUID) -> None:
        leave = await self.session.get(DoctorLeave, leave_id)
        if leave is None or (who.role == UserRole.DOCTOR and leave.doctor_id != who.doctor_id):
            raise NotFoundError("Leave not found.")
        await self.session.delete(leave)
        audit.record(self.session, who, "leave.delete", "doctor", leave.doctor_id, {"leave_id": str(leave_id)})
        await self.session.commit()

    # ------------------------------------------------------------------ stats
    async def stats(self) -> StatsOut:
        today, now = self.today(), self.clock()
        status_rows = await self.session.execute(
            select(Appointment.appointment_status, func.count())
            .where(Appointment.appointment_date == today, Appointment.deleted_at.is_(None))
            .group_by(Appointment.appointment_status)
        )
        by_status = {row[0]: row[1] for row in status_rows.all()}
        upcoming = await self.session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.appointment_status.in_(ACTIVE_STATUSES), Appointment.start_at > now)
        )
        doctors = await self.session.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.is_active.is_(True), Doctor.deleted_at.is_(None))
        )
        outbox_rows = await self.session.execute(
            select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status)
        )
        outbox = {row[0]: row[1] for row in outbox_rows.all()}
        return StatsOut(
            today=today,
            today_total=sum(by_status.values()),
            today_by_status={k.value: v for k, v in by_status.items()},
            upcoming_active=upcoming or 0,
            active_doctors=doctors or 0,
            notifications={
                s.value: outbox.get(s, 0) for s in (OutboxStatus.PENDING, OutboxStatus.FAILED, OutboxStatus.DEAD)
            },
        )
