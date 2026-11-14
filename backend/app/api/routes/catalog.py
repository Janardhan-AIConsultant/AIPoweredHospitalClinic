"""Public catalog endpoints (no authentication, no PII)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import DoctorOut, SpecializationOut
from app.services.catalog import CatalogService

router = APIRouter(tags=["catalog"])


def get_catalog_service(session: AsyncSession = Depends(get_session)) -> CatalogService:
    return CatalogService(CatalogRepository(session))


@router.get("/specializations", response_model=list[SpecializationOut])
async def list_specializations(svc: CatalogService = Depends(get_catalog_service)) -> list[SpecializationOut]:
    return await svc.specializations()


@router.get("/doctors", response_model=list[DoctorOut])
async def list_doctors(
    specialization_id: uuid.UUID | None = None, svc: CatalogService = Depends(get_catalog_service)
) -> list[DoctorOut]:
    return await svc.doctors(specialization_id)


@router.get("/doctors/{doctor_id}", response_model=DoctorOut)
async def get_doctor(doctor_id: uuid.UUID, svc: CatalogService = Depends(get_catalog_service)) -> DoctorOut:
    return await svc.doctor(doctor_id)
