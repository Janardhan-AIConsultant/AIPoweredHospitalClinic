"""Patient use-cases: find-or-create by phone with PII encrypted at rest."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.security import FieldCipher
from app.models import Patient
from app.repositories.patients import PatientRepository
from app.utils.phone import normalize_phone


class PatientService:
    def __init__(self, repo: PatientRepository, cipher: FieldCipher) -> None:
        self.repo = repo
        self.cipher = cipher

    async def get_or_create(
        self, full_name: str, phone: str, email: str | None = None, notification_consent: bool = False
    ) -> Patient:
        e164 = normalize_phone(phone)  # raises ValueError on invalid input
        phone_hash = self.cipher.hash_phone(e164)
        existing = await self.repo.get_by_phone_hash(phone_hash)
        if existing:
            return existing
        return self.repo.add(
            Patient(
                full_name=full_name.strip(),
                phone_encrypted=self.cipher.encrypt(e164),
                phone_hash=phone_hash,
                email_encrypted=self.cipher.encrypt(email.strip().lower()) if email else None,
                notification_consent=notification_consent,
                notification_consent_at=datetime.now(UTC) if notification_consent else None,
            )
        )

    def phone_of(self, patient: Patient) -> str:
        return self.cipher.decrypt(patient.phone_encrypted)
