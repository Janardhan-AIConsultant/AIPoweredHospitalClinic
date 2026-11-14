"""Read access to specializations and doctors (soft-deleted/inactive rows excluded)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Doctor, Specialization


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_specializations(self) -> Sequence[Specialization]:
        stmt = select(Specialization).where(Specialization.is_active.is_(True)).order_by(Specialization.name)
        return (await self.session.scalars(stmt)).all()

    async def list_doctors(self, specialization_id: uuid.UUID | None = None) -> Sequence[Doctor]:
        stmt = select(Doctor).where(Doctor.is_active.is_(True), Doctor.deleted_at.is_(None)).order_by(Doctor.full_name)
        if specialization_id:
            stmt = stmt.where(Doctor.specialization_id == specialization_id)
        return (await self.session.scalars(stmt)).unique().all()

    async def get_doctor(self, doctor_id: uuid.UUID) -> Doctor | None:
        stmt = select(Doctor).where(Doctor.id == doctor_id, Doctor.is_active.is_(True), Doctor.deleted_at.is_(None))
        return (await self.session.scalars(stmt)).unique().one_or_none()
