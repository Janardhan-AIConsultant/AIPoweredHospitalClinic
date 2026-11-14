"""WhatsApp Cloud API webhook (verification handshake + signed event delivery)."""

from __future__ import annotations

import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.booking import get_cipher
from app.core.config import Settings, get_settings
from app.core.exceptions import PermissionDeniedError, ValidationFailure
from app.core.security import FieldCipher
from app.database.session import get_session
from app.notifications.webhook import process_payload, verify_signature

router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp"])
MAX_BODY = 256 * 1024


@router.get("", response_class=PlainTextResponse)
async def verify(
    mode: str = Query("", alias="hub.mode"),
    token: str = Query("", alias="hub.verify_token"),
    challenge: str = Query("", alias="hub.challenge"),
    settings: Settings = Depends(get_settings),
) -> str:
    expected = settings.whatsapp_verify_token.get_secret_value()
    if mode != "subscribe" or not expected or not hmac.compare_digest(token, expected):
        raise PermissionDeniedError("Webhook verification failed.")
    return challenge


async def verified_body(request: Request, settings: Settings = Depends(get_settings)) -> bytes:
    """Read and authenticate the raw body. Declared first so unsigned requests never reach the DB or key setup."""
    body = await request.body()
    if len(body) > MAX_BODY:
        raise ValidationFailure("Payload too large.")
    secret = settings.whatsapp_app_secret.get_secret_value()
    if not verify_signature(secret, body, request.headers.get("x-hub-signature-256")):
        raise PermissionDeniedError("Invalid signature.")
    return body


@router.post("")
async def receive(
    body: bytes = Depends(verified_body),
    session: AsyncSession = Depends(get_session),
    cipher: FieldCipher = Depends(get_cipher),
) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise ValidationFailure("Invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValidationFailure("Invalid payload.")
    counts = await process_payload(session, cipher, payload)
    return {"status": "ok", **counts}
