"""Staff authentication: password login with lockout, rotating refresh tokens, user creation.

- Wrong email and wrong password are indistinguishable (same message, same work factor).
- 5 consecutive failures lock the account for 15 minutes.
- Refresh tokens are opaque, stored hashed, single use. Presenting an already-used token revokes
  the whole token family (theft detection). Two tabs refreshing at the same instant can trip this;
  the user simply logs in again.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, ValidationFailure
from app.core.principal import Principal
from app.core.security import create_access_token, hash_password, verify_password
from app.models import RefreshToken, User
from app.models.enums import UserRole
from app.services import audit
from app.utils.pii import mask_text
from app.utils.timezone import utcnow

MAX_FAILED = 5
LOCK_FOR = timedelta(minutes=15)
MIN_PASSWORD = 12
INVALID = "Invalid email or password."
_dummy_hash: str | None = None


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


async def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = await asyncio.to_thread(hash_password, "not-a-real-password")
    return _dummy_hash


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD or password.lower() == password or not any(c.isdigit() for c in password):
        raise ValidationFailure(
            f"Password must be at least {MIN_PASSWORD} characters with upper and lower case letters and a digit."
        )


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Callable[[], datetime] = utcnow) -> None:
        self.session, self.settings, self.clock = session, settings, clock

    # ----------------------------------------------------------------- login
    async def login(self, email: str, password: str) -> tuple[User, str, str]:
        now = self.clock()
        user = await self.session.scalar(
            select(User).where(User.email == email.strip().lower(), User.deleted_at.is_(None)).with_for_update()
        )
        locked = user is not None and user.locked_until is not None and user.locked_until > now
        if user is None or locked or not user.is_active:
            await verify_password_async(password, await _dummy())  # equalise timing
            await self.session.rollback()
            raise AuthenticationError(INVALID)
        if not await verify_password_async(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED:
                user.locked_until, user.failed_login_count = now + LOCK_FOR, 0
                details = {"email": mask_text(user.email)}
                audit.record(self.session, None, "auth.account_locked", "user", user.id, details)
            await self.session.commit()
            raise AuthenticationError(INVALID)
        user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
        access = self._access(user)
        refresh = self._issue_refresh(user.id, uuid.uuid4(), now)
        audit.record(self.session, Principal(user.id, user.role, user.doctor_id), "auth.login", "user", user.id)
        await self.session.commit()
        return user, access, refresh

    # --------------------------------------------------------------- refresh
    async def refresh(self, raw: str) -> tuple[User, str, str]:
        now = self.clock()
        token = await self.session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == _sha(raw)).with_for_update()
        )
        if token is None:
            await self.session.rollback()
            raise AuthenticationError()
        if token.revoked_at is not None:  # reuse of a rotated token: assume theft, kill the family
            await self._revoke_family(token.family_id, now)
            audit.record(self.session, None, "auth.refresh_reuse", "user", token.user_id)
            await self.session.commit()
            raise AuthenticationError()
        user = await self.session.get(User, token.user_id)
        if token.expires_at <= now or user is None or not user.is_active or user.deleted_at is not None:
            await self.session.rollback()
            raise AuthenticationError()
        token.revoked_at = now
        new = self._issue_refresh(user.id, token.family_id, now)
        access = self._access(user)
        await self.session.commit()
        return user, access, new

    async def logout(self, raw: str | None) -> None:
        if not raw:
            return
        token = await self.session.scalar(select(RefreshToken).where(RefreshToken.token_hash == _sha(raw)))
        if token is not None:
            await self._revoke_family(token.family_id, self.clock())
            await self.session.commit()

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        """Revoke every refresh token of a user (caller commits)."""
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=self.clock())
        )

    # ----------------------------------------------------------------- users
    async def create_user(
        self, email: str, password: str, role: UserRole, doctor_id: uuid.UUID | None, actor: Principal | None
    ) -> User:
        validate_password(password)
        if role == UserRole.PATIENT:
            raise ValidationFailure("Only ADMIN and DOCTOR accounts can be created here.")
        if (role == UserRole.DOCTOR) != (doctor_id is not None):
            raise ValidationFailure("A doctor_id is required for DOCTOR accounts and not allowed for ADMIN accounts.")
        user = User(
            email=email.strip().lower(),
            password_hash=await asyncio.to_thread(hash_password, password),
            role=role,
            doctor_id=doctor_id,
        )
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("A user with this email or doctor already exists.") from exc
        audit.record(self.session, actor, "user.create", "user", user.id, {"role": role.value})
        await self.session.commit()
        return user

    # --------------------------------------------------------------- helpers
    def _access(self, user: User) -> str:
        extra = {"did": str(user.doctor_id)} if user.doctor_id else None
        return create_access_token(self.settings, str(user.id), user.role.value, extra)

    def _issue_refresh(self, user_id: uuid.UUID, family: uuid.UUID, now: datetime) -> str:
        raw = secrets.token_urlsafe(48)
        self.session.add(
            RefreshToken(
                user_id=user_id,
                family_id=family,
                token_hash=_sha(raw),
                expires_at=now + timedelta(days=self.settings.jwt_refresh_ttl_days),
            )
        )
        return raw

    async def _revoke_family(self, family: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
