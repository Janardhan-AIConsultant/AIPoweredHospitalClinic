"""Public booking endpoints: list slots, create an appointment (guest checkout)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import FieldCipher
from app.database.session import get_session
from app.repositories.booking import BookingRepository
from app.repositories.patients import PatientRepository
from app.schemas.booking import AppointmentOut, BookingRequest, SlotOut, SlotsResponse
from app.services.availability import AvailabilityService
from app.services.booking import BookCommand, BookingService
from app.services.patients import PatientService
from app.utils.timezone import utcnow

router = APIRouter(tags=["booking"])


def get_cipher(settings: Settings = Depends(get_settings)) -> FieldCipher:
    return FieldCipher.from_settings(settings)


def get_clock() -> Callable[[], datetime]:
    return utcnow  # overridable in tests


def get_availability_service(
    session: AsyncSession = Depends(get_session), clock: Callable[[], datetime] = Depends(get_clock)
) -> AvailabilityService:
    return AvailabilityService(BookingRepository(session), clock)


def get_booking_service(
    session: AsyncSession = Depends(get_session),
    cipher: FieldCipher = Depends(get_cipher),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> BookingService:
    return BookingService(
        session, BookingRepository(session), PatientService(PatientRepository(session), cipher), clock
    )


@router.get("/doctors/{doctor_id}/slots", response_model=SlotsResponse)
async def list_slots(
    doctor_id: uuid.UUID, date: date, svc: AvailabilityService = Depends(get_availability_service)
) -> SlotsResponse:
    slots = await svc.slots_for(doctor_id, date)
    return SlotsResponse(
        doctor_id=doctor_id, date=date, slots=[SlotOut(start_time=s.start_time, end_time=s.end_time) for s in slots]
    )


@router.post("/appointments", response_model=AppointmentOut, status_code=201)
async def create_appointment(
    body: BookingRequest,
    idempotency_key: str | None = Header(default=None, min_length=8, max_length=64),
    svc: BookingService = Depends(get_booking_service),
) -> AppointmentOut:
    return await svc.book(
        BookCommand(
            doctor_id=body.doctor_id,
            day=body.date,
            start_time=body.start_time,
            patient_name=body.patient_name,
            phone=body.phone,
            email=body.email,
            reason=body.reason_for_visit,
            notification_consent=body.notification_consent,
            idempotency_key=idempotency_key,
        )
    )
