"""Audit trail. Rows are added to the caller's session so they commit with the change they describe."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_ctx
from app.core.principal import Principal
from app.models import AuditLog
from app.utils.pii import redact_mapping


def record(
    session: AsyncSession,
    actor: Principal | None,
    action: str,
    entity_type: str,
    entity_id: object | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    rid = request_id_ctx.get()
    session.add(
        AuditLog(
            actor_user_id=actor.user_id if actor else None,
            actor_role=actor.role.value if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=redact_mapping(details) if details else None,
            request_id=None if rid == "-" else rid,
        )
    )
