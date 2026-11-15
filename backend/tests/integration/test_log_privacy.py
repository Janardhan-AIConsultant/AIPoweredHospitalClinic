import io
import logging
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.ai.llm import MockLLM
from app.api.routes.booking import get_cipher, get_clock
from app.api.routes.chat import get_llm
from app.core.config import Settings, get_settings
from app.core.logging import JsonFormatter
from app.core.security import FieldCipher
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Doctor

NOW = datetime(2030, 1, 1, tzinfo=UTC)
SETTINGS = Settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40)
CIPHER = FieldCipher(Fernet.generate_key().decode(), "hash-key")
NAME, PHONE, EMAIL = "Zyxwvut Quillfeather", "9876543210", "zyx.quill@example.com"


@pytest_asyncio.fixture
async def client_and_logs(maker):
    async with maker() as s:
        await seed_demo_data(s)
        await s.commit()
        doctor_id = await s.scalar(select(Doctor.id).where(Doctor.full_name == "Dr. Anil Kumar"))
    app = create_app(SETTINGS)
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides.update(
        {
            get_session: _session,
            get_settings: lambda: SETTINGS,
            get_cipher: lambda: CIPHER,
            get_clock: lambda: lambda: NOW,
            get_llm: lambda: MockLLM(),
        }
    )
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield c, buf, doctor_id
    finally:
        logging.getLogger().removeHandler(handler)


async def test_booking_and_chat_never_write_personal_data_to_logs(client_and_logs):
    client, buf, doctor_id = client_and_logs
    r = await client.post(
        "/appointments",
        headers={"Idempotency-Key": "k-privacy-1"},
        json={
            "doctor_id": str(doctor_id),
            "date": "2030-01-07",
            "start_time": "09:00",
            "patient_name": NAME,
            "phone": PHONE,
            "email": EMAIL,
            "reason_for_visit": "private reason text",
            "notification_consent": True,
        },
    )
    assert r.status_code == 201
    await client.post("/chat", json={"messages": [{"role": "user", "content": f"call me on {PHONE} or {EMAIL}"}]})
    await client.post("/patient/otp/request", json={"phone": PHONE})
    await client.post("/auth/login", json={"email": "someone@clinic.test", "password": "Secret-Pass-123"})

    logs = buf.getvalue()
    assert "request" in logs  # logging really was captured
    for secret in (NAME, "Quillfeather", PHONE, EMAIL, "private reason text", "Secret-Pass-123"):
        assert secret not in logs, f"{secret!r} leaked into logs"
