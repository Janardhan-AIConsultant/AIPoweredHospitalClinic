"""Cryptographic primitives: PII field encryption, phone lookup hash, passwords, JWTs.

Keys come from Settings and are never logged. Missing keys raise a clear error
at use time (not import time) so mock/local runs without PII features still boot.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.exceptions import AuthenticationError

JWT_ALGORITHM = "HS256"
_hasher = PasswordHasher()


class FieldCipher:
    """Fernet encryption for PII at rest plus a deterministic HMAC for equality lookup."""

    def __init__(self, encryption_key: str, hash_key: str) -> None:
        if not encryption_key or not hash_key:
            raise RuntimeError("FIELD_ENCRYPTION_KEY and PHONE_HASH_KEY must be configured")
        self._fernet = Fernet(encryption_key.encode())
        self._hash_key = hash_key.encode()

    @classmethod
    def from_settings(cls, settings: Settings) -> FieldCipher:
        return cls(settings.field_encryption_key.get_secret_value(), settings.phone_hash_key.get_secret_value())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt value (wrong key or corrupted data)") from exc

    def hash_phone(self, e164_phone: str) -> str:
        return hmac.new(self._hash_key, e164_phone.encode(), hashlib.sha256).hexdigest()

    def hash_otp(self, challenge_id: str, phone_hash: str, code: str) -> str:
        """HMAC of a one-time code, bound to its challenge and phone (domain-separated from phone hashes)."""
        message = f"otp|{challenge_id}|{phone_hash}|{code}".encode()
        return hmac.new(self._hash_key, message, hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(settings: Settings, subject: str, role: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_ttl_minutes),
        "jti": uuid.uuid4().hex,
        **(extra or {}),
    }
    return jwt.encode(claims, settings.jwt_secret_key.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(settings: Settings, token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid or expired token.") from exc
