"""The authenticated staff member for the current request."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models.enums import UserRole


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    role: UserRole
    doctor_id: uuid.UUID | None = None
