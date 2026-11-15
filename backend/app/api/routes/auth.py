"""Staff authentication. The refresh token lives in an HttpOnly cookie scoped to ``/auth``;
the short-lived access token is returned in the body and kept in memory by the frontend.

Cookie endpoints (refresh, logout) require a custom ``X-CSRF-Token`` header. Browsers only send
custom headers cross-origin after a CORS preflight, which only the configured frontend passes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_principal
from app.api.routes.booking import get_clock
from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.principal import Principal
from app.core.rate_limit import RateLimiter, rate_limited
from app.database.session import get_session
from app.models import User
from app.schemas.staff import LoginRequest, LoginResponse, UserOut
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "refresh_token"
_login_limiter = RateLimiter(limit=10, window_seconds=60)
_refresh_limiter = RateLimiter(limit=30, window_seconds=60)


def get_auth_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    clock: Callable[[], datetime] = Depends(get_clock),
) -> AuthService:
    return AuthService(session, settings, clock)


def _set_cookie(response: Response, settings: Settings, value: str) -> None:
    samesite = settings.cookie_samesite
    secure = settings.app_env in ("production", "staging") or samesite == "none"  # "none" requires Secure
    response.set_cookie(
        COOKIE,
        value,
        max_age=settings.jwt_refresh_ttl_days * 86400,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path=settings.auth_cookie_path,
    )


def _require_csrf_header(x_csrf_token: str | None) -> None:
    if not x_csrf_token:
        raise PermissionDeniedError("Missing CSRF header.")


def _body(user: User, access: str, settings: Settings) -> LoginResponse:
    return LoginResponse(
        access_token=access,
        expires_in=settings.jwt_access_ttl_minutes * 60,
        user=UserOut(id=user.id, email=user.email, role=user.role, doctor_id=user.doctor_id, is_active=user.is_active),
    )


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(rate_limited(_login_limiter))])
async def login(
    body: LoginRequest,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    user, access, refresh = await svc.login(body.email, body.password)
    _set_cookie(response, settings, refresh)
    return _body(user, access, settings)


@router.post("/refresh", response_model=LoginResponse, dependencies=[Depends(rate_limited(_refresh_limiter))])
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
    svc: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    _require_csrf_header(x_csrf_token)
    if not refresh_token:
        raise AuthenticationError()
    user, access, new = await svc.refresh(refresh_token)
    _set_cookie(response, settings, new)
    return _body(user, access, settings)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None),
    svc: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> None:
    _require_csrf_header(x_csrf_token)
    await svc.logout(refresh_token)
    response.delete_cookie(COOKIE, path=settings.auth_cookie_path)


@router.get("/me", response_model=UserOut)
async def me(
    principal: Principal = Depends(current_principal), session: AsyncSession = Depends(get_session)
) -> UserOut:
    user = await session.get(User, principal.user_id)
    assert user is not None  # current_principal just loaded it
    return UserOut(id=user.id, email=user.email, role=user.role, doctor_id=user.doctor_id, is_active=user.is_active)
