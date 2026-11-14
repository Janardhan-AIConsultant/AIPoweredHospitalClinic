"""Authentication / RBAC dependencies for staff endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.principal import Principal
from app.core.security import decode_access_token
from app.database.session import get_session
from app.models import User
from app.models.enums import UserRole

STAFF = (UserRole.ADMIN, UserRole.DOCTOR)


async def current_principal(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> Principal:
    """Validate the bearer token, then re-check the account in the database (role/active changes apply at once)."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError()
    claims = decode_access_token(settings, token)
    if claims.get("role") not in {r.value for r in STAFF}:
        raise AuthenticationError()
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except ValueError as exc:
        raise AuthenticationError() from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError()
    return Principal(user.id, user.role, user.doctor_id)


def require_roles(*roles: UserRole) -> Callable[..., Principal]:
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise PermissionDeniedError()
        return principal

    return dependency


require_admin = require_roles(UserRole.ADMIN)
require_doctor = require_roles(UserRole.DOCTOR)
