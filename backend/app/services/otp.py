"""WhatsApp OTP for patient self-service (view, cancel, reschedule own appointments).

Security properties:
- Requests never reveal whether a number has appointments: the caller always sees the same reply.
- Codes are 6 random digits, valid 10 minutes, stored only as an HMAC, usable once.
- At most 5 wrong guesses per code; at most 3 codes per number per 15 minutes, 60 s apart.
- Codes are sent directly (not through the outbox) and are never logged or persisted in clear.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ValidationFailure
from app.core.security import FieldCipher
from app.models import Appointment, OtpChallenge
from app.notifications import templates
from app.notifications.whatsapp import WhatsAppSender
from app.utils.phone import normalize_phone
from app.utils.timezone import utcnow

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_CODES = 3
CODES_WINDOW = timedelta(minutes=15)
COOLDOWN = timedelta(seconds=60)
INVALID = "Invalid or expired code."


class OtpService:
    def __init__(
        self,
        session: AsyncSession,
        cipher: FieldCipher,
        sender: WhatsAppSender,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session, self.cipher, self.sender, self.clock = session, cipher, sender, clock

    def _hash(self, raw_phone: str) -> tuple[str, str]:
        try:
            e164 = normalize_phone(raw_phone)
        except ValueError as exc:
            raise ValidationFailure(str(exc)) from exc
        return e164, self.cipher.hash_phone(e164)

    async def request_code(self, raw_phone: str) -> None:
        """Send a code if (and only if) this number has appointments. Silent otherwise."""
        e164, phone_hash = self._hash(raw_phone)
        now = self.clock()
        has_appointments = await self.session.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.patient_phone_hash == phone_hash)
        )
        if not has_appointments:
            return
        recent = (
            await self.session.scalars(
                select(OtpChallenge.created_at).where(
                    OtpChallenge.phone_hash == phone_hash, OtpChallenge.created_at > now - CODES_WINDOW
                )
            )
        ).all()
        if len(recent) >= MAX_CODES or any(c > now - COOLDOWN for c in recent):
            logger.info("otp_throttled", extra={"operation": "otp.request"})
            return
        code = f"{secrets.randbelow(10**6):06d}"
        challenge_id = uuid.uuid4()
        self.session.add(
            OtpChallenge(
                id=challenge_id,
                phone_hash=phone_hash,
                code_hash=self.cipher.hash_otp(str(challenge_id), phone_hash, code),
                expires_at=now + CODE_TTL,
                created_at=now,
            )
        )
        await self.session.commit()
        try:
            await self.sender.send_template(e164, templates.OTP, [code], button_text=code)
        except Exception:  # noqa: BLE001 - the caller must not learn whether a send happened
            logger.warning("otp_send_failed", extra={"operation": "otp.request"})

    async def verify_code(self, raw_phone: str, code: str) -> str:
        """Return the phone hash on success; raise AuthenticationError otherwise."""
        _, phone_hash = self._hash(raw_phone)
        now = self.clock()
        challenge = await self.session.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.phone_hash == phone_hash,
                OtpChallenge.consumed_at.is_(None),
                OtpChallenge.expires_at > now,
                OtpChallenge.attempts < MAX_ATTEMPTS,
            )
            .order_by(OtpChallenge.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if challenge is None:
            await self.session.rollback()
            raise AuthenticationError(INVALID)
        challenge.attempts += 1  # counted before comparing, and committed even on failure
        expected = self.cipher.hash_otp(str(challenge.id), phone_hash, code)
        ok = hmac.compare_digest(expected, challenge.code_hash)
        if ok:
            challenge.consumed_at = now
        await self.session.commit()
        if not ok:
            raise AuthenticationError(INVALID)
        return phone_hash
