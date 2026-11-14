"""Catalog use-cases: specializations and doctors for public browsing."""

from __future__ import annotations

import uuid

from app.core.exceptions import NotFoundError
from app.models import Doctor
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import DoctorOut, ScheduleOut, SpecializationOut


class CatalogService:
    def __init__(self, repo: CatalogRepository) -> None:
        self.repo = repo

    async def specializations(self) -> list[SpecializationOut]:
        return [SpecializationOut.model_validate(s) for s in await self.repo.list_specializations()]

    @staticmethod
    def _public(doc: Doctor) -> DoctorOut:
        """Build the public view; only active schedules are exposed."""
        out = DoctorOut.model_validate(doc)
        out.schedules = [ScheduleOut.model_validate(x) for x in doc.schedules if x.is_active]
        return out

    async def doctors(self, specialization_id: uuid.UUID | None = None) -> list[DoctorOut]:
        return [self._public(d) for d in await self.repo.list_doctors(specialization_id)]

    async def doctor(self, doctor_id: uuid.UUID) -> DoctorOut:
        doc = await self.repo.get_doctor(doctor_id)
        if doc is None:
            raise NotFoundError("Doctor not found.")
        return self._public(doc)
