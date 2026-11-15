import time

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.exceptions import AuthenticationError
from app.core.security import (
    FieldCipher,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

KEY = Fernet.generate_key().decode()


def cipher(hash_key="h1"):
    return FieldCipher(KEY, hash_key)


def test_encrypt_roundtrip_and_nondeterministic():
    c = cipher()
    a, b = c.encrypt("+919876543210"), c.encrypt("+919876543210")
    assert a != b and "9876543210" not in a
    assert c.decrypt(a) == "+919876543210"


def test_decrypt_wrong_key_or_garbage():
    token = cipher().encrypt("x")
    with pytest.raises(ValueError):
        FieldCipher(Fernet.generate_key().decode(), "h").decrypt(token)
    with pytest.raises(ValueError):
        cipher().decrypt("garbage")


def test_phone_hash_deterministic_keyed():
    assert cipher().hash_phone("+919876543210") == cipher().hash_phone("+919876543210")
    assert cipher("h1").hash_phone("+919876543210") != cipher("h2").hash_phone("+919876543210")
    assert len(cipher().hash_phone("+919876543210")) == 64


def test_missing_keys_raise():
    with pytest.raises(RuntimeError):
        FieldCipher("", "")


def test_password_hash_verify():
    h = hash_password("S3cret!pass")
    assert h != "S3cret!pass" and verify_password("S3cret!pass", h)
    assert not verify_password("wrong", h) and not verify_password("x", "not-a-hash")


def test_jwt_roundtrip_and_tamper():
    s = Settings(_env_file=None, jwt_secret_key="k" * 40)
    claims = decode_access_token(s, create_access_token(s, "u1", "ADMIN"))
    assert claims["sub"] == "u1" and claims["role"] == "ADMIN"
    other = Settings(_env_file=None, jwt_secret_key="z" * 40)
    with pytest.raises(AuthenticationError):
        decode_access_token(other, create_access_token(s, "u1", "ADMIN"))
    with pytest.raises(AuthenticationError):
        decode_access_token(s, "not.a.token")


def test_jwt_expired():
    s = Settings(_env_file=None, jwt_secret_key="k" * 40)
    token = create_access_token(s, "u1", "ADMIN", extra={"exp": int(time.time()) - 10})
    with pytest.raises(AuthenticationError):
        decode_access_token(s, token)
