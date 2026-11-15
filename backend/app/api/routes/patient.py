"""Patient self-service: WhatsApp OTP login, then view / cancel / reschedule own appointments."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.booking import get_booking_service, get_cipher, get_clock
from app.api.routes.internal import get_sender
from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.rate_limit import RateLimiter, rate_limited
from app.core.security import FieldCipher, create_access_token, decode_access_token
from app.database.session import get_session
from app.models import Appointment
from app.notifications.whatsapp import WhatsAppSender
from app.schemas.booking import AppointmentOut
from app.schemas.patient import CancelRequest, OtpRequest, OtpRequested, OtpVerify, RescheduleRequest, TokenOut
from app.services.booking import BookingService, to_out
from app.services.otp import OtpService

router = APIRouter(prefix="/patient", tags=["patient"])

_request_limiter = RateLimiter(limit=5, window_seconds=60)
_verify_limiter = RateLimiter(limit=10, window_seconds=60)
_write_limiter = RateLimiter(limit=20, window_seconds=60)
HISTORY = timedelta(days=30)
PATIENT_ROLE = "patient"


def get_otp_service(
    session: AsyncSession = Depends(get_session),
    cipher: FieldCipher = Depends(get_cipher),
    sender: WhatsAppSender = Depends(get_sender),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> OtpService:
    return OtpService(session, cipher, sender, clock)


def current_phone_hash(
    authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)
) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError()
    claims = decode_access_token(settings, token)
    if claims.get("role") != PATIENT_ROLE:
        raise AuthenticationError()
    return str(claims["sub"])


@router.post(
    "/otp/request",
    response_model=OtpRequested,
    status_code=202,
    dependencies=[Depends(rate_limited(_request_limiter))],
)
async def request_otp(body: OtpRequest, svc: OtpService = Depends(get_otp_service)) -> OtpRequested:
    await svc.request_code(body.phone)
    return OtpRequested()


@router.post("/otp/verify", response_model=TokenOut, dependencies=[Depends(rate_limited(_verify_limiter))])
async def verify_otp(
    body: OtpVerify, svc: OtpService = Depends(get_otp_service), settings: Settings = Depends(get_settings)
) -> TokenOut:
    phone_hash = await svc.verify_code(body.phone, body.code)
    token = create_access_token(settings, phone_hash, PATIENT_ROLE)
    return TokenOut(access_token=token, expires_in=settings.jwt_access_ttl_minutes * 60)


@router.get("/appointments", response_model=list[AppointmentOut])
async def my_appointments(
    phone_hash: str = Depends(current_phone_hash),
    session: AsyncSession = Depends(get_session),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> list[AppointmentOut]:
    rows = await session.scalars(
        select(Appointment)
        .where(
            Appointment.patient_phone_hash == phone_hash,
            Appointment.deleted_at.is_(None),
            Appointment.start_at >= clock() - HISTORY,
        )
        .order_by(Appointment.start_at.desc())
        .limit(50)
    )
    return [to_out(a, a.doctor) for a in rows]


async def _owned(booking: BookingService, reference: str, phone_hash: str) -> str:
    ref = reference.strip().upper()
    appt = await booking.repo.get_by_reference(ref)
    if appt is None or appt.patient_phone_hash != phone_hash:
        raise NotFoundError("Appointment not found.")  # same answer for "missing" and "someone else's"
    return ref


@router.post(
    "/appointments/{reference}/cancel",
    response_model=AppointmentOut,
    dependencies=[Depends(rate_limited(_write_limiter))],
)
async def cancel(
    reference: str,
    body: CancelRequest | None = None,
    phone_hash: str = Depends(current_phone_hash),
    booking: BookingService = Depends(get_booking_service),
) -> AppointmentOut:
    ref = await _owned(booking, reference, phone_hash)
    return await booking.cancel(ref, body.reason if body else None)


@router.post(
    "/appointments/{reference}/reschedule",
    response_model=AppointmentOut,
    dependencies=[Depends(rate_limited(_write_limiter))],
)
async def reschedule(
    reference: str,
    body: RescheduleRequest,
    phone_hash: str = Depends(current_phone_hash),
    booking: BookingService = Depends(get_booking_service),
) -> AppointmentOut:
    ref = await _owned(booking, reference, phone_hash)
    return await booking.reschedule(ref, body.date, body.start_time.replace(second=0, microsecond=0))
