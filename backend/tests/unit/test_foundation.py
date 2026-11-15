import json
import logging
from datetime import date, time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import JsonFormatter
from app.main import create_app
from app.utils.phone import normalize_phone
from app.utils.pii import mask_phone, mask_text, redact_mapping
from app.core.config import get_settings
from app.utils.timezone import to_clinic, to_utc


def make_client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, app_env="test")), raise_server_exceptions=False)


# --- config -----------------------------------------------------------
def test_defaults_are_mock_mode():
    s = Settings(_env_file=None)
    assert (s.llm_mode, s.chroma_mode, s.whatsapp_mode) == ("mock", "mock", "mock")


def test_production_requires_secrets():
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None, app_env="production")
    assert "DATABASE_URL" in str(e.value) and "JWT_SECRET_KEY" in str(e.value)


def test_production_valid_config():
    s = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql://x",
        jwt_secret_key="k" * 40,
        field_encryption_key="f",
        phone_hash_key="p",
        cron_secret="c",
        frontend_url="https://clinic.example",
    )
    assert s.is_production


def test_invalid_log_level():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="LOUD")


def test_live_mode_needs_all_credentials():
    assert Settings(_env_file=None, xai_api_key="k").llm_mode == "mock"
    assert Settings(_env_file=None, xai_api_key="k", xai_model="m").llm_mode == "live"


# --- pii / phone / tz -------------------------------------------------
def test_mask_phone_and_text():
    assert mask_phone("+919876543210") == "+91********10"
    assert "9876543210" not in mask_text("call +91 98765 43210 or a.b@x.com")
    assert "a.b@" not in mask_text("a.b@x.com")


def test_redact_mapping_hides_secrets():
    out = redact_mapping({"otp": "123456", "n": {"token": "t", "p": "+919876543210"}})
    assert out["otp"] == "[REDACTED]" and out["n"]["token"] == "[REDACTED]"
    assert "9876543210" not in out["n"]["p"]


@pytest.mark.parametrize("raw", ["9876543210", "09876543210", "+91 98765 43210"])
def test_normalize_phone_ok(raw):
    assert normalize_phone(raw) == "+919876543210"


@pytest.mark.parametrize("raw", ["12345", "abc", "+911234567890", ""])
def test_normalize_phone_rejects(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_timezone_roundtrip():
    utc = to_utc(date(2026, 1, 5), time(9, 0))
    assert utc.hour == 3 and utc.minute == 30  # IST = UTC+5:30
    assert to_clinic(utc).hour == 9


# --- logging ----------------------------------------------------------
def test_log_formatter_masks_pii():
    rec = logging.LogRecord("t", logging.INFO, "", 0, "booked for +919876543210", (), None)
    rec.phone = "+919876543210"
    data = json.loads(JsonFormatter().format(rec))
    assert "9876543210" not in json.dumps(data)
    assert {"timestamp", "level", "module", "request_id"} <= data.keys()


# --- http -------------------------------------------------------------
def test_health_and_headers():
    r = make_client().get("/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Request-ID"]


def test_ready_reports_mock_modes_without_secrets():
    body = make_client().get("/health/ready").json()
    assert body["integrations"]["llm"] == "mock"


def test_payload_too_large():
    r = make_client().post("/health", content=b"x", headers={"content-length": "999999"})
    assert r.status_code == 413


def test_unknown_route_uses_error_envelope():
    r = make_client().get("/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "http_error"


def test_unhandled_error_hides_details():
    app = create_app(Settings(_env_file=None, app_env="test"))

    @app.get("/boom")
    async def boom():
        raise RuntimeError("secret internals")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500 and "secret" not in r.text


def test_readiness_without_database_reports_not_configured():
    # Isolate from any local backend/.env: the readiness route resolves settings via get_settings().
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, app_env="test")
    body = TestClient(app).get("/health/ready").json()
    assert body["database"] == "not_configured" and body["status"] == "ok"


def test_cors_preflight_allows_idempotency_key_header():
    r = make_client().options(
        "/appointments",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,idempotency-key",
        },
    )
    assert r.status_code == 200 and "idempotency-key" in r.headers["access-control-allow-headers"].lower()
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_allows_credentialed_staff_calls_from_frontend_only():
    ok = make_client().options(
        "/auth/refresh",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-token,authorization",
        },
    )
    assert ok.status_code == 200 and ok.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in ok.headers["access-control-allow-headers"].lower()
    evil = make_client().options(
        "/auth/refresh",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in evil.headers
