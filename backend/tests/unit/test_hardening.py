import uuid
from datetime import date, time

import pytest
from fastapi.testclient import TestClient

from app.ai.proposals import create_proposal, read_proposal
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ValidationFailure
from app.core.security import create_access_token, decode_access_token
from app.main import create_app

SETTINGS = Settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, max_request_bytes=2048)


def client() -> TestClient:
    return TestClient(create_app(SETTINGS), raise_server_exceptions=False)


def chunks(total: int, size: int = 512):
    for _ in range(total // size):
        yield b"x" * size


def test_chunked_body_over_the_limit_is_rejected_without_content_length():
    r = client().post("/chat", content=chunks(10_000), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    assert r.headers["x-content-type-options"] == "nosniff"  # still gets the security headers


def test_chunked_body_under_the_limit_is_processed():
    r = client().post("/chat", content=chunks(1024), headers={"content-type": "application/json"})
    assert r.status_code == 422  # reaches validation: the limiter did not interfere


def test_webhook_rejects_oversized_and_unsigned_bodies():
    from app.database.session import get_session

    app = create_app(SETTINGS)

    async def no_db():
        yield None  # the signature check must fail before any database work

    app.dependency_overrides[get_session] = no_db
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/webhooks/whatsapp", content=chunks(50_000)).status_code == 413
    assert c.post("/webhooks/whatsapp", content=b"{}").status_code == 403


def test_security_headers_on_errors_too():
    r = client().get("/definitely-missing")
    assert r.status_code == 404
    for h in ("X-Frame-Options", "Strict-Transport-Security", "Content-Security-Policy", "Referrer-Policy"):
        assert h in r.headers
    assert r.headers["cache-control"] == "no-store"


def test_docs_are_hidden_in_production():
    prod = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql://u:p@h/db",
        jwt_secret_key="s" * 40,
        field_encryption_key="k",
        phone_hash_key="p",
        cron_secret="c",
        frontend_url="https://clinic.example",
    )
    c = TestClient(create_app(prod), raise_server_exceptions=False)
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_token_types_cannot_be_swapped():
    proposal = create_proposal(SETTINGS, uuid.uuid4(), date(2030, 1, 2), time(10))
    with pytest.raises(AuthenticationError):
        decode_access_token(SETTINGS, proposal)  # a booking proposal is not an access token
    access = create_access_token(SETTINGS, "sub", "ADMIN")
    with pytest.raises(ValidationFailure):
        read_proposal(SETTINGS, access)  # and an access token is not a booking proposal


def test_tokens_signed_with_another_key_or_alg_none_are_rejected():
    import jwt

    other = Settings(_env_file=None, jwt_secret_key="z" * 40)
    with pytest.raises(AuthenticationError):
        decode_access_token(SETTINGS, create_access_token(other, "sub", "ADMIN"))
    unsigned = jwt.encode({"sub": "x", "role": "ADMIN", "exp": 9999999999}, key="", algorithm="none")
    with pytest.raises(AuthenticationError):
        decode_access_token(SETTINGS, unsigned)


def test_secrets_never_appear_in_settings_repr():
    s = Settings(_env_file=None, jwt_secret_key="super-secret-jwt-key-value-123456", xai_api_key="xai-secret-key")
    text = repr(s) + str(s.model_dump())
    assert "super-secret-jwt-key-value" not in text and "xai-secret-key" not in text
