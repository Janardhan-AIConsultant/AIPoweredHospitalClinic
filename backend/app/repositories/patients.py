"""Patient persistence. Lookups use the HMAC phone hash, never the plaintext."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Patient


class PatientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_phone_hash(self, phone_hash: str) -> Patient | None:
        stmt = select(Patient).where(Patient.phone_hash == phone_hash, Patient.deleted_at.is_(None))
        return await self.session.scalar(stmt)

    def add(self, patient: Patient) -> Patient:
        self.session.add(patient)
        return patient
