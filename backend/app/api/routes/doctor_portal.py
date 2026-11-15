"""Doctor dashboard API (DOCTOR only; always scoped to the doctor's own patients and leave)."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import require_doctor
from app.api.routes.admin import get_staff_service
from app.core.principal import Principal
from app.models.enums import AppointmentStatus
from app.schemas.booking import AppointmentOut
from app.schemas.staff import (
    AppointmentPage,
    CancelBody,
    LeaveOut,
    LeaveRequest,
    StaffAppointmentOut,
    StatusUpdate,
)
from app.services.staff import StaffService

router = APIRouter(prefix="/doctor", tags=["doctor"])


@router.get("/appointments", response_model=AppointmentPage)
async def appointments(
    date_from: date | None = None,
    date_to: date | None = None,
    status: AppointmentStatus | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    who: Principal = Depends(require_doctor),
    svc: StaffService = Depends(get_staff_service),
) -> AppointmentPage:
    return await svc.list_appointments(
        who, date_from=date_from, date_to=date_to, doctor_id=None, status=status, limit=limit, offset=offset
    )


@router.post("/appointments/{reference}/status", response_model=StaffAppointmentOut)
async def set_status(
    reference: str,
    body: StatusUpdate,
    who: Principal = Depends(require_doctor),
    svc: StaffService = Depends(get_staff_service),
) -> StaffAppointmentOut:
    return await svc.set_status(who, reference, AppointmentStatus(body.status))


@router.post("/appointments/{reference}/cancel", response_model=AppointmentOut)
async def cancel(
    reference: str,
    body: CancelBody | None = None,
    who: Principal = Depends(require_doctor),
    svc: StaffService = Depends(get_staff_service),
) -> AppointmentOut:
    return await svc.cancel(who, reference, body.reason if body else None)


@router.get("/leave", response_model=list[LeaveOut])
async def list_leave(
    who: Principal = Depends(require_doctor), svc: StaffService = Depends(get_staff_service)
) -> list[LeaveOut]:
    return await svc.list_leave(who, None)


@router.post("/leave", response_model=LeaveOut, status_code=201)
async def add_leave(
    body: LeaveRequest, who: Principal = Depends(require_doctor), svc: StaffService = Depends(get_staff_service)
) -> LeaveOut:
    return await svc.add_leave(who, None, body.start_date, body.end_date, body.reason)


@router.delete("/leave/{leave_id}", status_code=204)
async def delete_leave(
    leave_id: uuid.UUID, who: Principal = Depends(require_doctor), svc: StaffService = Depends(get_staff_service)
) -> Response:
    await svc.delete_leave(who, leave_id)
    return Response(status_code=204)
