"""Admin dashboard API (ADMIN only)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.routes.auth import get_auth_service
from app.api.routes.booking import get_booking_service, get_cipher, get_clock
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ValidationFailure
from app.core.principal import Principal
from app.core.security import FieldCipher
from app.database.session import get_session
from app.models import AuditLog, Doctor, User
from app.models.enums import AppointmentStatus
from app.schemas.booking import AppointmentOut
from app.schemas.staff import (
    AdminDoctorOut,
    AppointmentPage,
    AuditOut,
    CancelBody,
    CreateUserRequest,
    DoctorPatch,
    LeaveOut,
    LeaveRequest,
    StaffAppointmentOut,
    StatsOut,
    StatusUpdate,
    UserOut,
    UserPatch,
)
from app.services import audit
from app.services.auth import AuthService
from app.services.booking import BookingService
from app.services.staff import StaffService

router = APIRouter(prefix="/admin", tags=["admin"])


def get_staff_service(
    session: AsyncSession = Depends(get_session),
    cipher: FieldCipher = Depends(get_cipher),
    booking: BookingService = Depends(get_booking_service),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> StaffService:
    return StaffService(session, cipher, booking, clock)


@router.get("/stats", response_model=StatsOut)
async def stats(_: Principal = Depends(require_admin), svc: StaffService = Depends(get_staff_service)) -> StatsOut:
    return await svc.stats()


@router.get("/appointments", response_model=AppointmentPage)
async def appointments(
    date_from: date | None = None,
    date_to: date | None = None,
    doctor_id: uuid.UUID | None = None,
    status: AppointmentStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> AppointmentPage:
    return await svc.list_appointments(
        who, date_from=date_from, date_to=date_to, doctor_id=doctor_id, status=status, limit=limit, offset=offset
    )


@router.post("/appointments/{reference}/cancel", response_model=AppointmentOut)
async def cancel(
    reference: str,
    body: CancelBody | None = None,
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> AppointmentOut:
    return await svc.cancel(who, reference, body.reason if body else None)


@router.post("/appointments/{reference}/status", response_model=StaffAppointmentOut)
async def set_status(
    reference: str,
    body: StatusUpdate,
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> StaffAppointmentOut:
    return await svc.set_status(who, reference, AppointmentStatus(body.status))


@router.get("/doctors", response_model=list[AdminDoctorOut])
async def doctors(
    _: Principal = Depends(require_admin), svc: StaffService = Depends(get_staff_service)
) -> list[AdminDoctorOut]:
    return await svc.list_doctors()


@router.patch("/doctors/{doctor_id}", response_model=AdminDoctorOut)
async def update_doctor(
    doctor_id: uuid.UUID,
    body: DoctorPatch,
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> AdminDoctorOut:
    return await svc.update_doctor(who, doctor_id, body)


@router.get("/leave", response_model=list[LeaveOut])
async def list_leave(
    doctor_id: uuid.UUID | None = None,
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> list[LeaveOut]:
    return await svc.list_leave(who, doctor_id)


@router.post("/doctors/{doctor_id}/leave", response_model=LeaveOut, status_code=201)
async def add_leave(
    doctor_id: uuid.UUID,
    body: LeaveRequest,
    who: Principal = Depends(require_admin),
    svc: StaffService = Depends(get_staff_service),
) -> LeaveOut:
    return await svc.add_leave(who, doctor_id, body.start_date, body.end_date, body.reason)


@router.delete("/leave/{leave_id}", status_code=204)
async def delete_leave(
    leave_id: uuid.UUID, who: Principal = Depends(require_admin), svc: StaffService = Depends(get_staff_service)
) -> Response:
    await svc.delete_leave(who, leave_id)
    return Response(status_code=204)


@router.get("/audit-logs", response_model=list[AuditOut])
async def audit_logs(
    action: str | None = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AuditOut]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [
        AuditOut(
            id=r.id,
            created_at=r.created_at,
            actor_user_id=r.actor_user_id,
            actor_role=r.actor_role,
            action=r.action,
            entity_type=r.entity_type,
            entity_id=r.entity_id,
            details=r.details,
        )
        for r in await session.scalars(stmt)
    ]


# ---------------------------------------------------------------------- users
def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role, doctor_id=u.doctor_id, is_active=u.is_active)


@router.get("/users", response_model=list[UserOut])
async def users(_: Principal = Depends(require_admin), session: AsyncSession = Depends(get_session)) -> list[UserOut]:
    rows = await session.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.email))
    return [_user_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(
    body: CreateUserRequest,
    who: Principal = Depends(require_admin),
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    if body.doctor_id is not None:
        exists = await session.scalar(
            select(func.count()).select_from(Doctor).where(Doctor.id == body.doctor_id, Doctor.deleted_at.is_(None))
        )
        if not exists:
            raise NotFoundError("Doctor not found.")
    return _user_out(await auth.create_user(body.email, body.password, body.role, body.doctor_id, who))


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: uuid.UUID,
    body: UserPatch,
    who: Principal = Depends(require_admin),
    auth: AuthService = Depends(get_auth_service),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("User not found.")
    if user.id == who.user_id and not body.is_active:
        raise ValidationFailure("You cannot deactivate your own account.")
    user.is_active = body.is_active
    if not body.is_active:
        await auth.revoke_all(user.id)
    audit.record(session, who, "user.activate" if body.is_active else "user.deactivate", "user", user.id)
    await session.commit()
    return _user_out(user)


_ = Settings, get_settings  # re-exported for dependency overrides in tests
