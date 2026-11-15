import re
import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.api.routes import patient as patient_routes
from app.api.routes.booking import get_cipher, get_clock
from app.api.routes.internal import get_sender
from app.core.config import Settings, get_settings
from app.core.security import FieldCipher, create_access_token
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Doctor, NotificationOutbox, OtpChallenge
from app.notifications import templates
from app.notifications.whatsapp import MockWhatsApp
from app.services.otp import MAX_ATTEMPTS, OtpService
from tests.integration.test_booking import DAY, NOW, cmd, make_service

CIPHER = FieldCipher(Fernet.generate_key().decode(), "hash-key")
SETTINGS = Settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40)
PHONE = "9876543210"
OTHER = "9123456780"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest_asyncio.fixture
async def doc(maker) -> uuid.UUID:
    async with maker() as s:
        await seed_demo_data(s)
        await s.commit()
        return await s.scalar(select(Doctor.id).where(Doctor.full_name == "Dr. Anil Kumar"))


def service(s):
    svc = make_service(s)
    svc.patients.cipher = CIPHER
    return svc


async def book(maker, doc, phone=PHONE, **kw):
    async with maker() as s:
        return await service(s).book(cmd(doc, phone=phone, **kw))


@pytest_asyncio.fixture
async def env(maker, doc):
    for lim in (patient_routes._request_limiter, patient_routes._verify_limiter, patient_routes._write_limiter):
        lim._hits.clear()
    clock, sender = Clock(), MockWhatsApp()
    app = create_app(SETTINGS)

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides.update(
        {
            get_session: _session,
            get_settings: lambda: SETTINGS,
            get_cipher: lambda: CIPHER,
            get_clock: lambda: clock,
            get_sender: lambda: sender,
        }
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, clock, sender


def last_code(sender: MockWhatsApp) -> str:
    to, template, params = sender.sent[-1]
    assert template == templates.OTP and re.fullmatch(r"\d{6}", params[0])
    return params[0]


async def login(client, clock, sender, phone=PHONE) -> dict[str, str]:
    clock.now += timedelta(minutes=20)  # clear any throttle window from earlier requests
    assert (await client.post("/patient/otp/request", json={"phone": phone})).status_code == 202
    r = await client.post("/patient/otp/verify", json={"phone": phone, "code": last_code(sender)})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------------- OTP flow
async def test_request_is_indistinguishable_for_unknown_numbers(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    known = await client.post("/patient/otp/request", json={"phone": PHONE})
    unknown = await client.post("/patient/otp/request", json={"phone": OTHER})
    assert known.status_code == unknown.status_code == 202 and known.json() == unknown.json()
    assert len(sender.sent) == 1 and sender.sent[0][0] == "+919876543210"  # only the real number got a code


async def test_code_is_not_stored_or_queued_in_clear(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    code = last_code(sender)
    async with maker() as s:
        ch = await s.scalar(select(OtpChallenge))
        outbox = (await s.scalars(select(NotificationOutbox))).all()
    assert code not in ch.code_hash and len(ch.code_hash) == 64
    assert all(code not in str(o.payload) for o in outbox)  # outbox only has the booking confirmation
    assert sender.sent[0][2] == [code]


async def test_verify_success_returns_token_and_code_is_single_use(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    code = last_code(sender)
    r = await client.post("/patient/otp/verify", json={"phone": PHONE, "code": code})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer" and r.json()["expires_in"] == 900
    again = await client.post("/patient/otp/verify", json={"phone": PHONE, "code": code})
    assert again.status_code == 401


async def test_wrong_codes_lock_the_challenge_even_for_the_right_code(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    good = last_code(sender)
    bad = "000000" if good != "000000" else "111111"
    for _ in range(MAX_ATTEMPTS):
        assert (await client.post("/patient/otp/verify", json={"phone": PHONE, "code": bad})).status_code == 401
    assert (await client.post("/patient/otp/verify", json={"phone": PHONE, "code": good})).status_code == 401


async def test_expired_code_and_unknown_phone_fail_identically(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    code = last_code(sender)
    clock.now += timedelta(minutes=11)
    expired = await client.post("/patient/otp/verify", json={"phone": PHONE, "code": code})
    unknown = await client.post("/patient/otp/verify", json={"phone": OTHER, "code": code})
    assert expired.status_code == unknown.status_code == 401
    assert expired.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_newer_code_supersedes_older_and_throttling_applies(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    first = last_code(sender)
    await client.post("/patient/otp/request", json={"phone": PHONE})  # within 60s cooldown: ignored
    assert len(sender.sent) == 1
    clock.now += timedelta(seconds=61)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    second = last_code(sender)
    assert len(sender.sent) == 2
    if first != second:
        assert (await client.post("/patient/otp/verify", json={"phone": PHONE, "code": first})).status_code == 401
    clock.now += timedelta(seconds=61)
    await client.post("/patient/otp/request", json={"phone": PHONE})
    clock.now += timedelta(seconds=61)
    await client.post("/patient/otp/request", json={"phone": PHONE})  # 4th within 15 min: ignored
    assert len(sender.sent) == 3


async def test_send_failure_is_invisible_to_the_caller(env, maker, doc):
    client, clock, _ = env

    class Broken:
        async def send_template(self, *a, **k):
            raise RuntimeError("boom +919876543210")

    await book(maker, doc)
    async with maker() as s:
        await OtpService(s, CIPHER, Broken(), clock).request_code(PHONE)  # must not raise


async def test_input_validation(env):
    client, _, _ = env
    assert (await client.post("/patient/otp/request", json={"phone": "12"})).status_code == 422
    assert (await client.post("/patient/otp/request", json={"phone": "abcdefgh"})).status_code == 422
    assert (await client.post("/patient/otp/verify", json={"phone": PHONE, "code": "12ab56"})).status_code == 422
    assert (await client.post("/patient/otp/verify", json={"phone": PHONE, "code": "12345"})).status_code == 422


async def test_ip_rate_limits(env):
    client, _, _ = env
    codes = [(await client.post("/patient/otp/request", json={"phone": PHONE})).status_code for _ in range(6)]
    assert codes[:5] == [202] * 5 and codes[5] == 429


# --------------------------------------------------------------- token checks
async def test_endpoints_require_a_patient_token(env):
    client, _, _ = env
    assert (await client.get("/patient/appointments")).status_code == 401
    assert (await client.get("/patient/appointments", headers={"Authorization": "Token abc"})).status_code == 401
    assert (await client.get("/patient/appointments", headers={"Authorization": "Bearer garbage"})).status_code == 401
    staff = create_access_token(SETTINGS, "someone", "admin")
    assert (await client.get("/patient/appointments", headers={"Authorization": f"Bearer {staff}"})).status_code == 401
    assert (await client.post("/patient/appointments/ABC/cancel")).status_code == 401


# -------------------------------------------------------------- appointments
async def test_lists_only_own_appointments(env, maker, doc):
    client, clock, sender = env
    mine = await book(maker, doc)
    await book(maker, doc, phone=OTHER, start=time(10))
    headers = await login(client, clock, sender)
    r = await client.get("/patient/appointments", headers=headers)
    assert r.status_code == 200
    assert [a["appointment_reference"] for a in r.json()] == [mine.appointment_reference]
    assert "9876543210" not in r.text


async def test_cancel_own_appointment_and_not_others(env, maker, doc):
    client, clock, sender = env
    mine = await book(maker, doc)
    theirs = await book(maker, doc, phone=OTHER, start=time(10))
    headers = await login(client, clock, sender)
    denied = await client.post(f"/patient/appointments/{theirs.appointment_reference}/cancel", headers=headers)
    missing = await client.post("/patient/appointments/NOPE000000/cancel", headers=headers)
    assert denied.status_code == missing.status_code == 404 and denied.json()["error"] == {
        **missing.json()["error"],
        "request_id": denied.json()["error"]["request_id"],
    }
    ok = await client.post(
        f"/patient/appointments/{mine.appointment_reference.lower()}/cancel", headers=headers, json={"reason": "busy"}
    )
    assert ok.status_code == 200 and ok.json()["status"] == "CANCELLED"
    again = await client.post(f"/patient/appointments/{mine.appointment_reference}/cancel", headers=headers)
    assert again.status_code == 409
    # the freed slot can be booked again
    await book(maker, doc, phone=OTHER, start=time(9))


async def test_reschedule_own_appointment(env, maker, doc):
    client, clock, sender = env
    mine = await book(maker, doc)
    headers = await login(client, clock, sender)
    clock.now = NOW  # back to the booking-time clock so the horizon still includes DAY
    url = f"/patient/appointments/{mine.appointment_reference}/reschedule"
    r = await client.post(url, headers=headers, json={"date": DAY.isoformat(), "start_time": "11:00"})
    assert r.status_code == 200 and r.json()["start_time"] == "11:00:00"
    assert r.json()["appointment_reference"] != mine.appointment_reference
    taken = await book(maker, doc, phone=OTHER, start=time(9, 30))
    clash = await client.post(
        f"/patient/appointments/{r.json()['appointment_reference']}/reschedule",
        headers=headers,
        json={"date": DAY.isoformat(), "start_time": "09:30"},
    )
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "slot_unavailable"
    assert taken.start_time == time(9, 30)
    old = await client.post(url, headers=headers, json={"date": DAY.isoformat(), "start_time": "12:00"})
    assert old.status_code == 409  # the original reference is no longer reschedulable


async def test_token_for_one_patient_cannot_touch_anothers_booking(env, maker, doc):
    client, clock, sender = env
    await book(maker, doc)
    theirs = await book(maker, doc, phone=OTHER, start=time(10))
    headers = await login(client, clock, sender)
    clock.now = NOW
    r = await client.post(
        f"/patient/appointments/{theirs.appointment_reference}/reschedule",
        headers=headers,
        json={"date": DAY.isoformat(), "start_time": "11:00"},
    )
    assert r.status_code == 404
    assert date(2030, 1, 7) == DAY and UTC
