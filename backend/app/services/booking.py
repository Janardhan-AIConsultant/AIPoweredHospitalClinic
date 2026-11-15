"""Transactional booking, cancellation and rescheduling.

Concurrency model (defence in depth):
1. ``SELECT ... FOR UPDATE`` on the doctor row serialises bookings per doctor.
2. Slots are recomputed *under that lock* with the same engine patients see.
3. The ``ex_appointments_no_overlap`` exclusion constraint is the final guarantee;
   a violation, deadlock or serialization failure is mapped to "slot unavailable".

The service owns the transaction (commit/rollback). Authorising *who* may cancel or
reschedule (OTP / admin / doctor) is the caller's responsibility.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, SlotUnavailableError, ValidationFailure
from app.models import Appointment, Doctor
from app.models.enums import ACTIVE_STATUSES, AppointmentStatus
from app.notifications import templates
from app.notifications.outbox import enqueue_for_appointment
from app.repositories.booking import BookingRepository
from app.schemas.booking import AppointmentOut
from app.services.availability import Slot, compute_slots
from app.services.patients import PatientService
from app.utils.phone import normalize_phone
from app.utils.timezone import utcnow

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40P01", "40001"}  # deadlock_detected, serialization_failure


@dataclass(frozen=True)
class BookCommand:
    doctor_id: uuid.UUID
    day: date
    start_time: time
    patient_name: str
    phone: str
    email: str | None = None
    reason: str | None = None
    notification_consent: bool = False
    idempotency_key: str | None = None


def to_out(appt: Appointment, doctor: Doctor) -> AppointmentOut:
    return AppointmentOut(
        appointment_reference=appt.appointment_reference,
        doctor_id=doctor.id,
        doctor_name=doctor.full_name,
        specialization=doctor.specialization.name,
        appointment_date=appt.appointment_date,
        start_time=appt.start_time,
        end_time=appt.end_time,
        consultation_fee=appt.consultation_fee,
        status=appt.appointment_status,
        patient_name=appt.patient_name,
        reason_for_visit=appt.reason_for_visit,
        notification_consent=appt.notification_consent,
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    orig = exc.orig
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)


class BookingService:
    def __init__(
        self,
        session: AsyncSession,
        repo: BookingRepository,
        patients: PatientService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session = session
        self.repo = repo
        self.patients = patients
        self.clock = clock

    # ------------------------------------------------------------------ book
    async def book(self, cmd: BookCommand) -> AppointmentOut:
        try:
            e164 = normalize_phone(cmd.phone)
        except ValueError as exc:
            raise ValidationFailure(str(exc)) from exc
        phone_hash = self.patients.cipher.hash_phone(e164)

        if cmd.idempotency_key:
            existing = await self.repo.get_by_idempotency_key(cmd.idempotency_key)
            if existing:
                return self._replay(existing, cmd, phone_hash)

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._book_once(cmd, phone_hash)
            except _Retry as retry:
                logger.info("booking_retry", extra={"operation": "book", "error_category": retry.reason})
                if retry.reason == "idempotency_key" and cmd.idempotency_key:
                    existing = await self.repo.get_by_idempotency_key(cmd.idempotency_key)
                    if existing:
                        return self._replay(existing, cmd, phone_hash)
                if attempt == _MAX_ATTEMPTS:
                    raise ConflictError("Could not complete the booking. Please try again.") from None
        raise ConflictError("Could not complete the booking. Please try again.")  # pragma: no cover

    async def _book_once(self, cmd: BookCommand, phone_hash: str) -> AppointmentOut:
        doctor = await self.repo.lock_doctor(cmd.doctor_id)
        if doctor is None:
            await self.session.rollback()
            raise NotFoundError("Doctor not found.")
        try:
            slot = await self._require_slot(doctor, cmd.day, cmd.start_time)
            patient = await self.patients.get_or_create(
                cmd.patient_name, cmd.phone, cmd.email, cmd.notification_consent
            )
            await self.session.flush()  # surfaces patient unique races early
            reference = await self.repo.next_reference(cmd.day)
            appt = Appointment(
                appointment_reference=reference,
                patient_id=patient.id,
                doctor_id=doctor.id,
                doctor=doctor,
                patient_name=cmd.patient_name.strip(),
                patient_phone_encrypted=patient.phone_encrypted,
                patient_phone_hash=phone_hash,
                reason_for_visit=cmd.reason,
                appointment_date=cmd.day,
                start_time=slot.start_time,
                end_time=slot.end_time,
                start_at=slot.start_at,
                end_at=slot.end_at,
                consultation_fee=Decimal(doctor.consultation_fee),
                appointment_status=AppointmentStatus.CONFIRMED,
                notification_consent=cmd.notification_consent,
                idempotency_key=cmd.idempotency_key,
            )
            self.repo.add(appt)
            await self.session.flush()
            await enqueue_for_appointment(self.session, appt, templates.CONFIRMATION, self.clock())
            result = to_out(appt, doctor)
            await self.session.commit()
            logger.info("appointment_booked", extra={"operation": "book", "doctor_id": str(doctor.id)})
            return result
        except (IntegrityError, DBAPIError) as exc:
            await self.session.rollback()
            self._classify(exc)
            raise  # pragma: no cover
        except Exception:
            await self.session.rollback()
            raise

    # ---------------------------------------------------------------- cancel
    async def cancel(self, reference: str, reason: str | None = None) -> AppointmentOut:
        appt = await self.repo.get_by_reference(reference)
        if appt is None:
            raise NotFoundError("Appointment not found.")
        doctor = await self.repo.lock_doctor(appt.doctor_id) or appt.doctor
        await self.session.refresh(appt)
        if appt.appointment_status not in ACTIVE_STATUSES:
            await self.session.rollback()
            raise ConflictError("This appointment can no longer be cancelled.")
        if appt.start_at <= self.clock():
            await self.session.rollback()
            raise ValidationFailure("Past appointments cannot be cancelled.")
        appt.appointment_status = AppointmentStatus.CANCELLED
        appt.cancelled_at = self.clock()
        appt.cancellation_reason = reason
        appt.version += 1
        await enqueue_for_appointment(self.session, appt, templates.CANCELLED, self.clock())
        result = to_out(appt, doctor)
        await self.session.commit()
        return result

    # ------------------------------------------------------------ reschedule
    async def reschedule(self, reference: str, new_day: date, new_start: time) -> AppointmentOut:
        """Move an appointment to a new slot with the same doctor, atomically."""
        old = await self.repo.get_by_reference(reference)
        if old is None:
            raise NotFoundError("Appointment not found.")
        doctor = await self.repo.lock_doctor(old.doctor_id)
        if doctor is None:
            await self.session.rollback()
            raise NotFoundError("Doctor not found.")
        try:
            await self.session.refresh(old)
            if old.appointment_status not in ACTIVE_STATUSES:
                raise ConflictError("This appointment can no longer be rescheduled.")
            if old.start_at <= self.clock():
                raise ValidationFailure("Past appointments cannot be rescheduled.")
            old.appointment_status = AppointmentStatus.RESCHEDULED  # frees the old slot within this tx
            old.version += 1
            await self.session.flush()
            slot = await self._require_slot(doctor, new_day, new_start)
            new_reference = await self.repo.next_reference(new_day)
            new = Appointment(
                appointment_reference=new_reference,
                patient_id=old.patient_id,
                doctor_id=doctor.id,
                doctor=doctor,
                patient_name=old.patient_name,
                patient_phone_encrypted=old.patient_phone_encrypted,
                patient_phone_hash=old.patient_phone_hash,
                reason_for_visit=old.reason_for_visit,
                appointment_date=new_day,
                start_time=slot.start_time,
                end_time=slot.end_time,
                start_at=slot.start_at,
                end_at=slot.end_at,
                consultation_fee=Decimal(doctor.consultation_fee),
                appointment_status=AppointmentStatus.CONFIRMED,
                notification_consent=old.notification_consent,
                rescheduled_from_id=old.id,
            )
            self.repo.add(new)
            await self.session.flush()
            await enqueue_for_appointment(self.session, new, templates.RESCHEDULED, self.clock())
            result = to_out(new, doctor)
            await self.session.commit()
            return result
        except (IntegrityError, DBAPIError) as exc:
            await self.session.rollback()
            self._classify(exc)
            raise  # pragma: no cover
        except Exception:
            await self.session.rollback()
            raise

    # --------------------------------------------------------------- helpers
    async def _require_slot(self, doctor: Doctor, day: date, start: time) -> Slot:
        slots = await compute_slots(self.repo, doctor, day, self.clock())
        slot = next((s for s in slots if s.start_time == start), None)
        if slot is None:
            raise SlotUnavailableError()
        return slot

    def _replay(self, existing: Appointment, cmd: BookCommand, phone_hash: str) -> AppointmentOut:
        same = (
            existing.doctor_id == cmd.doctor_id
            and existing.appointment_date == cmd.day
            and existing.start_time == cmd.start_time
            and existing.patient_phone_hash == phone_hash
        )
        if not same:
            raise ConflictError(
                "Idempotency key was already used for a different request.", code="idempotency_conflict"
            )
        return to_out(existing, existing.doctor)

    @staticmethod
    def _classify(exc: IntegrityError | DBAPIError) -> None:
        """Translate DB failures; raises SlotUnavailableError, ``_Retry`` or re-raises."""
        text = str(exc.orig)
        if isinstance(exc, IntegrityError):
            if "ex_appointments_no_overlap" in text:
                raise SlotUnavailableError() from exc
            if "idempotency_key" in text:
                raise _Retry("idempotency_key") from exc
            if "appointment_reference" in text:
                raise _Retry("reference_collision") from exc
            if "phone_hash" in text:
                raise _Retry("patient_race") from exc
        elif _sqlstate(exc) in _RETRYABLE_SQLSTATES or "deadlock" in text.lower():
            raise SlotUnavailableError() from exc
        raise exc


class _Retry(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
