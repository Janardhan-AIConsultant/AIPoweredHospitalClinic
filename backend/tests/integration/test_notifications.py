import hashlib
import hmac
import json
import uuid
from datetime import UTC, date, datetime, time, timedelta

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.api.routes.booking import get_cipher, get_clock
from app.api.routes.internal import get_maker, get_sender
from app.core.config import Settings, get_settings
from app.core.security import FieldCipher
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Appointment, Doctor, NotificationLog, NotificationOutbox, Patient
from app.models.enums import AppointmentStatus, OutboxStatus
from app.notifications import templates
from app.notifications.dispatcher import STALE_AFTER, drain
from app.notifications.outbox import enqueue_due_reminders
from app.notifications.whatsapp import MockWhatsApp, SendError
from tests.integration.test_booking import DAY, NOW, cmd, make_service

CIPHER = FieldCipher(Fernet.generate_key().decode(), "hash-key")
SETTINGS = Settings(
    _env_file=None,
    app_env="test",
    cron_secret="cron-secret",
    whatsapp_verify_token="verify-me",
    whatsapp_app_secret="app-secret",
)


def book_cmd(doctor_id, consent=True, **kw):
    c = cmd(doctor_id, **kw)
    return type(c)(**{**c.__dict__, "notification_consent": consent})


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


async def outbox(maker):
    async with maker() as s:
        return list((await s.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))).all())


# ----------------------------------------------------------------- enqueueing
async def test_booking_writes_outbox_in_same_transaction(maker, doc):
    async with maker() as s:
        out = await service(s).book(book_cmd(doc))
    rows = await outbox(maker)
    assert len(rows) == 1
    row = rows[0]
    assert row.template_name == templates.CONFIRMATION and row.status == OutboxStatus.PENDING
    assert row.payload["reference"] == out.appointment_reference and row.payload["doctor_name"] == "Dr. Anil Kumar"
    assert "9876543210" not in json.dumps(row.payload) and "9876543210" not in row.recipient_phone_encrypted
    assert CIPHER.decrypt(row.recipient_phone_encrypted) == "+919876543210"
    assert set(row.payload) == {"patient_name", "doctor_name", "date", "time", "reference"}  # no medical data


async def test_no_consent_no_message_and_failed_booking_leaves_no_message(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc, consent=False))
    assert await outbox(maker) == []
    async with maker() as s:
        await service(s).book(book_cmd(doc, start=time(9, 30), phone="9123456780"))
    with pytest.raises(Exception):  # noqa: B017, PT011 - same slot -> rolled back
        async with maker() as s:
            await service(s).book(book_cmd(doc, start=time(9, 30), phone="9123456781"))
    assert len(await outbox(maker)) == 1  # the failed attempt added nothing


async def test_cancel_and_reschedule_enqueue_messages(maker, doc):
    async with maker() as s:
        a = await service(s).book(book_cmd(doc))
    async with maker() as s:
        b = await service(s).reschedule(a.appointment_reference, DAY, time(10, 0))
    async with maker() as s:
        await service(s).cancel(b.appointment_reference)
    names = sorted(r.template_name for r in await outbox(maker))
    assert names == sorted([templates.CONFIRMATION, templates.RESCHEDULED, templates.CANCELLED])


async def test_reminders_are_idempotent_and_windowed(maker, doc):
    async with maker() as s:
        soon = await service(s).book(book_cmd(doc, day=date(2030, 1, 2), start=time(9, 0)))  # in 24h window
        await service(s).book(book_cmd(doc, day=DAY, start=time(9, 0), phone="9123456780"))  # a week away
    async with maker() as s:
        # 2030-01-02 09:00 IST = 03:30 UTC; "now" 12h earlier
        now = datetime(2030, 1, 1, 15, 30, tzinfo=UTC)
        assert await enqueue_due_reminders(s, now) == 1
        assert await enqueue_due_reminders(s, now) == 0
    reminders = [r for r in await outbox(maker) if r.template_name == templates.REMINDER]
    assert len(reminders) == 1 and reminders[0].payload["reference"] == soon.appointment_reference


# --------------------------------------------------------------------- drain
async def test_drain_sends_and_logs(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    sender = MockWhatsApp()
    res = await drain(maker, sender, CIPHER, clock=lambda: NOW + timedelta(minutes=1))
    assert (res.claimed, res.sent) == (1, 1)
    to, template, params = sender.sent[0]
    assert to == "+919876543210" and template == templates.CONFIRMATION and params[0] == "Asha"
    (row,) = await outbox(maker)
    assert row.status == OutboxStatus.SENT and row.attempts == 1
    async with maker() as s:
        log = await s.scalar(select(NotificationLog))
    assert log.status == "sent" and log.provider_message_id.startswith("mock-")
    again = await drain(maker, sender, CIPHER, clock=lambda: NOW + timedelta(minutes=2))
    assert again.claimed == 0 and len(sender.sent) == 1  # nothing is sent twice


async def test_transient_failure_retries_with_backoff_then_dead(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))

    class Flaky:
        calls = 0

        async def send_template(self, *a):
            Flaky.calls += 1
            raise SendError("down", permanent=False, code="http_503", http_status=503)

    t = NOW
    for attempt in range(1, 7):
        t += timedelta(hours=7)
        res = await drain(maker, Flaky(), CIPHER, clock=lambda t=t: t)
        assert res.claimed == 1
        (row,) = await outbox(maker)
        assert row.attempts == attempt
        assert row.status == (OutboxStatus.DEAD if attempt == 6 else OutboxStatus.FAILED)
    assert (await drain(maker, Flaky(), CIPHER, clock=lambda: t + timedelta(days=1))).claimed == 0
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(NotificationLog)) == 6


async def test_backoff_delays_next_attempt_and_permanent_error_is_dead_at_once(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))

    class Down:
        async def send_template(self, *a):
            raise SendError("down", permanent=False)

    await drain(maker, Down(), CIPHER, clock=lambda: NOW)
    assert (await drain(maker, MockWhatsApp(), CIPHER, clock=lambda: NOW + timedelta(seconds=30))).claimed == 0
    assert (await drain(maker, MockWhatsApp(), CIPHER, clock=lambda: NOW + timedelta(minutes=2))).sent == 1

    async with maker() as s:
        await service(s).book(book_cmd(doc, start=time(10), phone="9123456780"))

    class Bad:
        async def send_template(self, *a):
            raise SendError("bad template", permanent=True, code="http_400", http_status=400)

    res = await drain(maker, Bad(), CIPHER, clock=lambda: NOW + timedelta(hours=1))
    assert res.dead == 1


async def test_skips_cancelled_appointment_and_revoked_consent(maker, doc):
    async with maker() as s:
        a = await service(s).book(book_cmd(doc))
        await service(s).book(book_cmd(doc, start=time(10), phone="9123456780"))
    async with maker() as s:  # cancel the first before its confirmation is sent
        await service(s).cancel(a.appointment_reference)
    async with maker() as s:  # revoke consent on the second
        appt = await s.scalar(select(Appointment).where(Appointment.start_time == time(10)))
        appt.notification_consent = False
        await s.commit()
    sender = MockWhatsApp()
    res = await drain(maker, sender, CIPHER, clock=lambda: NOW + timedelta(minutes=1))
    statuses = {r.template_name: r.status for r in await outbox(maker)}
    assert res.skipped == 2 and res.sent == 1  # only the cancellation notice goes out
    assert [t for _, t, _ in sender.sent] == [templates.CANCELLED]
    assert statuses[templates.CONFIRMATION] == OutboxStatus.SKIPPED


async def test_stale_processing_rows_are_reclaimed_and_fresh_ones_are_not(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
        row = await s.scalar(select(NotificationOutbox))
        row.status, row.locked_at = OutboxStatus.PROCESSING, NOW
        await s.commit()
    sender = MockWhatsApp()
    assert (await drain(maker, sender, CIPHER, clock=lambda: NOW + STALE_AFTER / 2)).claimed == 0
    assert (await drain(maker, sender, CIPHER, clock=lambda: NOW + STALE_AFTER * 2)).sent == 1


async def test_budget_exhaustion_releases_unprocessed_rows(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    sender = MockWhatsApp()
    res = await drain(maker, sender, CIPHER, clock=lambda: NOW, budget_seconds=-1)
    assert res.claimed == 1 and res.sent == 0 and sender.sent == []
    (row,) = await outbox(maker)
    assert row.status == OutboxStatus.PENDING
    assert (await drain(maker, sender, CIPHER, clock=lambda: NOW)).sent == 1


async def test_undecryptable_phone_is_a_permanent_failure(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    wrong = FieldCipher(Fernet.generate_key().decode(), "hash-key")
    res = await drain(maker, MockWhatsApp(), wrong, clock=lambda: NOW)
    assert res.dead == 1


# ----------------------------------------------------------------------- HTTP
@pytest_asyncio.fixture
async def client(maker, doc):
    app = create_app(SETTINGS)
    sender = MockWhatsApp()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides.update(
        {
            get_session: _session,
            get_settings: lambda: SETTINGS,
            get_cipher: lambda: CIPHER,
            get_clock: lambda: lambda: NOW + timedelta(minutes=1),
            get_maker: lambda: maker,
            get_sender: lambda: sender,
        }
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.sender = sender  # type: ignore[attr-defined]
        yield c


def signed(body: dict, secret="app-secret"):  # noqa: S107
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}}


async def test_cron_endpoint_requires_secret_and_drains(client, maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    assert (await client.get("/internal/cron/notifications")).status_code == 401
    assert (
        await client.get("/internal/cron/notifications", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    ok = await client.get("/internal/cron/notifications", headers={"Authorization": "Bearer cron-secret"})
    assert ok.status_code == 200 and ok.json()["sent"] == 1 and len(client.sender.sent) == 1
    post = await client.post("/internal/cron/notifications", headers={"Authorization": "Bearer cron-secret"})
    assert post.status_code == 200 and post.json()["claimed"] == 0


async def test_cron_endpoint_unconfigured_is_unavailable(maker, doc):
    app = create_app(SETTINGS)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, app_env="test")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/internal/cron/notifications", headers={"Authorization": "Bearer "})
    assert r.status_code == 503


async def test_webhook_verification_handshake(client):
    good = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"}
    r = await client.get("/webhooks/whatsapp", params=good)
    assert r.status_code == 200 and r.text == "12345"
    assert (await client.get("/webhooks/whatsapp", params={**good, "hub.verify_token": "no"})).status_code == 403
    assert (await client.get("/webhooks/whatsapp", params={**good, "hub.mode": "x"})).status_code == 403
    assert (await client.get("/webhooks/whatsapp")).status_code == 403


async def test_webhook_rejects_bad_signature_and_bad_bodies(client):
    body = {"entry": []}
    assert (await client.post("/webhooks/whatsapp", json=body)).status_code == 403
    assert (await client.post("/webhooks/whatsapp", **signed(body, secret="wrong"))).status_code == 403
    raw = b"not json"
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    r = await client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 422
    raw = b"[1]"
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    assert (
        await client.post("/webhooks/whatsapp", content=raw, headers={"X-Hub-Signature-256": sig})
    ).status_code == 422
    big = b" " * (256 * 1024 + 1)
    assert (await client.post("/webhooks/whatsapp", content=big)).status_code == 413


async def test_webhook_records_delivery_statuses_once(client, maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    await drain(maker, MockWhatsApp(), CIPHER, clock=lambda: NOW)
    async with maker() as s:
        mid = await s.scalar(select(NotificationLog.provider_message_id))

    def status(st, errors=None):
        s = {"id": mid, "status": st}
        if errors:
            s["errors"] = errors
        return {"entry": [{"changes": [{"value": {"statuses": [s, {"id": "unknown", "status": "read"}]}}]}]}

    r = await client.post("/webhooks/whatsapp", **signed(status("delivered")))
    assert r.status_code == 200 and r.json()["statuses"] == 1
    assert (await client.post("/webhooks/whatsapp", **signed(status("delivered")))).json()["statuses"] == 0
    assert (await client.post("/webhooks/whatsapp", **signed(status("read")))).json()["statuses"] == 1
    await client.post("/webhooks/whatsapp", **signed(status("failed", [{"code": 131026}])))
    async with maker() as s:
        logs = (await s.scalars(select(NotificationLog).order_by(NotificationLog.created_at))).all()
    assert [entry.status for entry in logs] == ["sent", "delivered", "read", "failed"]
    assert logs[-1].error_code == "131026"


async def test_stop_reply_revokes_consent_for_future_messages(client, maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
        patient = await s.scalar(select(Patient))
        patient.notification_consent = True
        await s.commit()
    stop = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "919876543210", "type": "text", "text": {"body": " STOP "}},
        {"from": "919876543210", "type": "text", "text": {"body": "hello"}},
        {"from": "garbage", "type": "text", "text": {"body": "stop"}},
        {"from": "919876543210", "type": "image"},
    ]}}]}]}  # fmt: skip
    r = await client.post("/webhooks/whatsapp", **signed(stop))
    assert r.status_code == 200 and r.json()["opt_outs"] == 1
    async with maker() as s:
        assert (await s.scalar(select(Patient))).notification_consent is False
        assert (await s.scalar(select(Appointment))).notification_consent is False
    res = await drain(maker, MockWhatsApp(), CIPHER, clock=lambda: NOW)
    assert res.skipped == 1 and res.sent == 0


async def test_booking_status_not_changed_by_notifications(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    await drain(maker, MockWhatsApp(), CIPHER, clock=lambda: NOW)
    async with maker() as s:
        assert (await s.scalar(select(Appointment))).appointment_status == AppointmentStatus.CONFIRMED


async def test_cron_never_drains_with_the_mock_sender_in_production(maker, doc):
    async with maker() as s:
        await service(s).book(book_cmd(doc))
    prod = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql://u:p@h/db",
        jwt_secret_key="s" * 40,
        field_encryption_key=Fernet.generate_key().decode(),
        phone_hash_key="p",
        cron_secret="cron-secret",
        frontend_url="https://clinic.example",
    )
    app = create_app(prod)
    sender = MockWhatsApp()

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides.update(
        {
            get_session: _session,
            get_settings: lambda: prod,
            get_cipher: lambda: CIPHER,
            get_clock: lambda: lambda: NOW + timedelta(minutes=1),
            get_maker: lambda: maker,
            get_sender: lambda: sender,
        }
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/internal/cron/notifications", headers={"Authorization": "Bearer cron-secret"})
    assert r.status_code == 200 and r.json()["skipped"] == "whatsapp_not_configured"
    assert sender.sent == []
    (row,) = await outbox(maker)
    assert row.status == OutboxStatus.PENDING  # still waiting for real credentials


async def test_cron_purges_old_short_lived_data_but_keeps_recent_and_pending(maker, doc):
    from app.models import AuditLog, OtpChallenge, RefreshToken, User
    from app.models.enums import UserRole
    from app.services.retention import purge_expired

    now = NOW + timedelta(days=200)
    async with maker() as s:
        await service(s).book(book_cmd(doc))
        await service(s).book(book_cmd(doc, start=time(10), phone="9123456780"))
        old_sent, pending = (await s.scalars(select(NotificationOutbox).order_by(NotificationOutbox.dedupe_key))).all()
        old_sent.status = OutboxStatus.SENT
        old_sent.updated_at = NOW  # finished long ago -> purged
        pending.updated_at = NOW  # old but still PENDING -> must survive
        user = User(email="u@x.test", password_hash="x", role=UserRole.ADMIN)
        s.add(user)
        await s.flush()
        fam = uuid.uuid4()
        day = timedelta(days=1)
        tokens = [  # (hash, expires_at, revoked_at, purged?)
            ("expired-long-ago", now - 8 * day, None, True),
            ("revoked-long-ago", now + day, now - 31 * day, True),
            ("valid", now + day, None, False),
            ("revoked-recently", now + day, now - 2 * day, False),
        ]
        s.add_all(
            [
                RefreshToken(user_id=user.id, family_id=fam, token_hash=h, expires_at=e, revoked_at=r)
                for h, e, r, _ in tokens
            ]
        )
        s.add_all(
            [
                OtpChallenge(phone_hash="h", code_hash="old", expires_at=NOW, created_at=NOW),
                OtpChallenge(phone_hash="h", code_hash="new", expires_at=now, created_at=now),
                AuditLog(action="keep.me", entity_type="x"),
            ]
        )
        await s.commit()
    async with maker() as s:
        counts = await purge_expired(s, now)
    assert counts == {"otp_challenges": 1, "refresh_tokens": 2, "outbox": 1}
    async with maker() as s:
        kept = set((await s.scalars(select(RefreshToken.token_hash))).all())
        assert kept == {"valid", "revoked-recently"}
        assert await s.scalar(select(func.count()).select_from(OtpChallenge)) == 1
        remaining = (await s.scalars(select(NotificationOutbox))).all()
        assert [r.status for r in remaining] == [OutboxStatus.PENDING]
        assert await s.scalar(select(func.count()).select_from(AuditLog)) == 1  # audit logs are never purged
