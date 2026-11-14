import json
import uuid
from datetime import UTC, datetime, time, timedelta

import httpx
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.api.routes import auth as auth_routes
from app.api.routes.booking import get_cipher, get_clock
from app.core.config import Settings, get_settings
from app.core.security import FieldCipher, create_access_token, hash_password
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Appointment, AuditLog, Doctor, NotificationOutbox, RefreshToken, User
from app.models.enums import UserRole
from tests.integration.test_booking import DAY, NOW, cmd, make_service

CIPHER = FieldCipher(Fernet.generate_key().decode(), "hash-key")
SETTINGS = Settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40)
PASSWORD = "Str0ng-Passw0rd!"
CSRF = {"X-CSRF-Token": "1"}


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest_asyncio.fixture
async def world(maker):
    """Seeded doctors, one admin and one account per of two doctors."""
    async with maker() as s:
        await seed_demo_data(s)
        await s.commit()
        anil = await s.scalar(select(Doctor).where(Doctor.full_name == "Dr. Anil Kumar"))
        rahul = await s.scalar(select(Doctor).where(Doctor.full_name == "Dr. Rahul Reddy"))
        pw = hash_password(PASSWORD)
        s.add_all(
            [
                User(email="admin@clinic.test", password_hash=pw, role=UserRole.ADMIN),
                User(email="anil@clinic.test", password_hash=pw, role=UserRole.DOCTOR, doctor_id=anil.id),
                User(email="rahul@clinic.test", password_hash=pw, role=UserRole.DOCTOR, doctor_id=rahul.id),
            ]
        )
        await s.commit()
        return {"anil": anil.id, "rahul": rahul.id}


@pytest_asyncio.fixture
async def env(maker, world):
    auth_routes._login_limiter._hits.clear()
    auth_routes._refresh_limiter._hits.clear()
    clock = Clock()
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
        }
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, clock, maker, world


async def login(client, who="admin", password=PASSWORD):
    r = await client.post("/auth/login", json={"email": f"{who}@clinic.test", "password": password})
    return r


async def token(client, who="admin") -> dict[str, str]:
    r = await login(client, who)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def book(maker, doc, phone="9876543210", start=time(9), name="Asha Rao"):
    async def run():
        async with maker() as s:
            svc = make_service(s)
            svc.patients.cipher = CIPHER
            c = cmd(doc, start=start, phone=phone, name=name)
            return await svc.book(type(c)(**{**c.__dict__, "notification_consent": True}))

    return run()


# ---------------------------------------------------------------------- auth
async def test_login_sets_http_only_cookie_and_returns_token(env):
    client, *_ = env
    r = await login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "ADMIN" and body["expires_in"] == 900 and "password" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "refresh_token=" in cookie and "httponly" in cookie and "path=/auth" in cookie
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "admin@clinic.test"


async def test_wrong_password_and_unknown_email_are_indistinguishable(env):
    client, *_ = env
    bad = await login(client, password="nope")
    unknown = await client.post("/auth/login", json={"email": "ghost@clinic.test", "password": "nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["error"]["message"] == unknown.json()["error"]["message"] == "Invalid email or password."


async def test_account_locks_after_five_failures_and_unlocks_later(env):
    client, clock, maker, _ = env
    for _ in range(5):
        assert (await login(client, password="wrong")).status_code == 401
    assert (await login(client)).status_code == 401  # correct password, but locked
    clock.now += timedelta(minutes=16)
    assert (await login(client)).status_code == 200
    async with maker() as s:
        actions = (await s.scalars(select(AuditLog.action))).all()
    assert "auth.account_locked" in actions and "auth.login" in actions


async def test_deactivated_account_cannot_login(env):
    client, _, maker, _ = env
    async with maker() as s:
        u = await s.scalar(select(User).where(User.email == "anil@clinic.test"))
        u.is_active = False
        await s.commit()
    assert (await login(client, "anil")).status_code == 401


async def test_refresh_requires_cookie_and_csrf_header(env):
    client, *_ = env
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code == 401  # no cookie yet
    await login(client)
    assert (await client.post("/auth/refresh")).status_code == 403  # cookie present, header missing
    ok = await client.post("/auth/refresh", headers=CSRF)
    assert ok.status_code == 200 and ok.json()["access_token"]


async def test_refresh_rotates_and_reuse_revokes_the_family(env):
    client, _, maker, _ = env
    first = (await login(client)).cookies["refresh_token"]
    r = await client.post("/auth/refresh", headers=CSRF)
    second = r.cookies["refresh_token"]
    assert r.status_code == 200 and second != first
    client.cookies.set("refresh_token", first, path="/auth")  # attacker replays the old token
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code == 401
    client.cookies.set("refresh_token", second, path="/auth")  # the legitimate newer token is now dead too
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code == 401
    async with maker() as s:
        assert "auth.refresh_reuse" in (await s.scalars(select(AuditLog.action))).all()
        assert all(t.revoked_at for t in (await s.scalars(select(RefreshToken))).all())


async def test_logout_revokes_refresh_token(env):
    client, *_ = env
    await login(client)
    assert (await client.post("/auth/logout")).status_code == 403
    assert (await client.post("/auth/logout", headers=CSRF)).status_code == 204
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code == 401
    assert (await client.post("/auth/logout", headers=CSRF)).status_code == 204  # idempotent


async def test_expired_refresh_token_is_rejected(env):
    client, clock, *_ = env
    await login(client)
    clock.now += timedelta(days=8)
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code == 401


# ---------------------------------------------------------------------- RBAC
async def test_endpoints_reject_missing_wrong_and_forged_tokens(env):
    client, *_ = env
    for path in ("/admin/stats", "/doctor/appointments", "/auth/me"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers={"Authorization": "Bearer junk"})).status_code == 401
    patient = create_access_token(SETTINGS, "hash", "patient")
    assert (await client.get("/admin/stats", headers={"Authorization": f"Bearer {patient}"})).status_code == 401
    ghost = create_access_token(SETTINGS, str(uuid.uuid4()), "ADMIN")
    assert (await client.get("/admin/stats", headers={"Authorization": f"Bearer {ghost}"})).status_code == 401
    bad_sub = create_access_token(SETTINGS, "not-a-uuid", "ADMIN")
    assert (await client.get("/admin/stats", headers={"Authorization": f"Bearer {bad_sub}"})).status_code == 401


async def test_roles_cannot_cross_over(env):
    client, *_ = env
    admin, doctor = await token(client, "admin"), await token(client, "anil")
    assert (await client.get("/admin/stats", headers=doctor)).status_code == 403
    assert (await client.get("/admin/audit-logs", headers=doctor)).status_code == 403
    assert (await client.post("/admin/users", headers=doctor, json={})).status_code == 403
    assert (await client.get("/doctor/appointments", headers=admin)).status_code == 403
    assert (await client.get("/admin/stats", headers=admin)).status_code == 200


async def test_deactivation_takes_effect_on_existing_tokens_immediately(env):
    client, *_ = env
    admin, doctor = await token(client, "admin"), await token(client, "anil")
    assert (await client.get("/doctor/appointments", headers=doctor)).status_code == 200
    users = (await client.get("/admin/users", headers=admin)).json()
    anil = next(u for u in users if u["email"] == "anil@clinic.test")
    assert (
        await client.patch(f"/admin/users/{anil['id']}", headers=admin, json={"is_active": False})
    ).status_code == 200
    assert (await client.get("/doctor/appointments", headers=doctor)).status_code == 401
    assert (await client.post("/auth/refresh", headers=CSRF)).status_code in (200, 401)  # cookie belongs to admin


# --------------------------------------------------------------------- admin
async def test_admin_lists_filters_and_masks_phone(env):
    client, _, maker, w = env
    await book(maker, w["anil"])
    await book(maker, w["rahul"], phone="9123456780", start=time(10), name="Ravi Teja")
    admin = await token(client)
    page = (await client.get("/admin/appointments", headers=admin)).json()
    assert page["total"] == 2 and len(page["items"]) == 2
    assert "9876543210" not in json.dumps(page) and page["items"][0]["patient_phone_masked"].startswith("+91")
    only = (await client.get("/admin/appointments", headers=admin, params={"doctor_id": str(w["rahul"])})).json()
    assert [i["patient_name"] for i in only["items"]] == ["Ravi Teja"]
    window = {"date_from": "2030-02-01"}
    assert (await client.get("/admin/appointments", headers=admin, params=window)).json()["total"] == 0
    paged = (await client.get("/admin/appointments", headers=admin, params={"limit": 1, "offset": 1})).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1
    assert (await client.get("/admin/appointments", headers=admin, params={"limit": 500})).status_code == 422
    assert (await client.get("/admin/appointments", headers=admin, params={"status": "BOGUS"})).status_code == 422


async def test_admin_cancel_is_audited_and_notifies(env):
    client, _, maker, w = env
    appt = await book(maker, w["anil"])
    admin = await token(client)
    r = await client.post(
        f"/admin/appointments/{appt.appointment_reference}/cancel", headers=admin, json={"reason": "x"}
    )
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert (await client.post("/admin/appointments/NOPE/cancel", headers=admin)).status_code == 404
    async with maker() as s:
        rows = (await s.scalars(select(AuditLog).where(AuditLog.action == "appointment.cancel"))).all()
        templates_queued = {o.template_name for o in (await s.scalars(select(NotificationOutbox))).all()}
    assert len(rows) == 1 and rows[0].actor_role == "ADMIN" and "9876543210" not in json.dumps(rows[0].details)
    assert "appointment_cancelled" in templates_queued


async def test_status_update_rules(env):
    client, clock, maker, w = env
    appt = await book(maker, w["anil"])
    admin = await token(client)
    url = f"/admin/appointments/{appt.appointment_reference}/status"
    assert (await client.post(url, headers=admin, json={"status": "COMPLETED"})).status_code == 422  # not started
    assert (await client.post(url, headers=admin, json={"status": "CANCELLED"})).status_code == 422  # not allowed
    clock.now = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)  # after the 09:00 IST start
    done = await client.post(url, headers=admin, json={"status": "COMPLETED"})
    assert done.status_code == 200 and done.json()["status"] == "COMPLETED"
    assert (await client.post(url, headers=admin, json={"status": "NO_SHOW"})).status_code == 409
    assert (await client.get("/admin/stats", headers=admin)).status_code == 200


async def test_stats(env):
    client, _, maker, w = env
    await book(maker, w["anil"])
    stats = (await client.get("/admin/stats", headers=await token(client))).json()
    assert stats["active_doctors"] == 5 and stats["upcoming_active"] == 1
    assert stats["notifications"]["PENDING"] == 1 and stats["today_total"] == 0


async def test_admin_edits_doctor_and_leave_blocks_booking(env):
    client, _, maker, w = env
    await book(maker, w["anil"])
    admin = await token(client)
    docs = (await client.get("/admin/doctors", headers=admin)).json()
    assert next(d for d in docs if d["id"] == str(w["anil"]))["upcoming_appointments"] == 1
    r = await client.patch(
        f"/admin/doctors/{w['anil']}", headers=admin, json={"consultation_fee": "650", "bio": "New bio"}
    )
    assert r.status_code == 200 and float(r.json()["consultation_fee"]) == 650
    assert (await client.patch(f"/admin/doctors/{w['anil']}", headers=admin, json={})).status_code == 422
    assert (
        await client.patch(f"/admin/doctors/{w['anil']}", headers=admin, json={"is_active": None})
    ).status_code == 422
    assert (await client.patch(f"/admin/doctors/{uuid.uuid4()}", headers=admin, json={"bio": "x"})).status_code == 404
    assert (
        await client.patch(f"/admin/doctors/{w['anil']}", headers=admin, json={"consultation_fee": -1})
    ).status_code == 422

    leave = await client.post(
        f"/admin/doctors/{w['anil']}/leave",
        headers=admin,
        json={"start_date": DAY.isoformat(), "end_date": DAY.isoformat(), "reason": "conference"},
    )
    assert leave.status_code == 201 and leave.json()["affected_appointments"] == 1  # reported, not auto-cancelled
    slots = await client.get(f"/doctors/{w['anil']}/slots", params={"date": DAY.isoformat()})
    assert slots.json()["slots"] == []
    bad = {"start_date": "2030-01-05", "end_date": "2030-01-04"}
    assert (await client.post(f"/admin/doctors/{w['anil']}/leave", headers=admin, json=bad)).status_code == 422
    past = {"start_date": "2029-12-01", "end_date": "2029-12-02"}
    assert (await client.post(f"/admin/doctors/{w['anil']}/leave", headers=admin, json=past)).status_code == 422
    listed = (await client.get("/admin/leave", headers=admin)).json()
    assert len(listed) == 1
    assert (await client.delete(f"/admin/leave/{listed[0]['id']}", headers=admin)).status_code == 204
    assert (await client.delete(f"/admin/leave/{listed[0]['id']}", headers=admin)).status_code == 404
    assert (await client.get(f"/doctors/{w['anil']}/slots", params={"date": DAY.isoformat()})).json()["slots"]


async def test_admin_user_management(env):
    client, _, maker, w = env
    admin = await token(client)
    spec = {"email": "new.doc@clinic.test", "password": PASSWORD, "role": "DOCTOR"}
    free = await client.post("/admin/users", headers=admin, json={**spec, "doctor_id": str(uuid.uuid4())})
    assert free.status_code == 404
    async with maker() as s:
        other = await s.scalar(select(Doctor.id).where(Doctor.full_name.like("%Priya%")))
    made = await client.post("/admin/users", headers=admin, json={**spec, "doctor_id": str(other)})
    assert made.status_code == 201 and "password" not in made.text
    dupe = await client.post("/admin/users", headers=admin, json={**spec, "doctor_id": str(other)})
    assert dupe.status_code == 409
    weak = await client.post(
        "/admin/users", headers=admin, json={**spec, "email": "w@clinic.test", "password": "short"}
    )
    assert weak.status_code == 422
    no_doc = await client.post("/admin/users", headers=admin, json={**spec, "email": "x@clinic.test"})
    assert no_doc.status_code == 422
    patient = {**spec, "email": "p@clinic.test", "role": "PATIENT"}
    assert (await client.post("/admin/users", headers=admin, json=patient)).status_code == 422
    admin_with_doc = {**spec, "email": "y@clinic.test", "role": "ADMIN", "doctor_id": str(other)}
    assert (await client.post("/admin/users", headers=admin, json=admin_with_doc)).status_code == 422
    me = (await client.get("/auth/me", headers=admin)).json()
    assert (await client.patch(f"/admin/users/{me['id']}", headers=admin, json={"is_active": False})).status_code == 422
    assert (
        await client.patch(f"/admin/users/{uuid.uuid4()}", headers=admin, json={"is_active": False})
    ).status_code == 404
    ok = await client.post("/auth/login", json={"email": "NEW.DOC@clinic.test", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["user"]["doctor_id"] == str(other)


async def test_audit_log_endpoint_filters_and_has_no_secrets(env):
    client, *_ = env
    admin = await token(client)
    await client.post("/auth/login", json={"email": "admin@clinic.test", "password": "wrong-password-1"})
    logs = (await client.get("/admin/audit-logs", headers=admin, params={"action": "auth.login"})).json()
    assert logs and all(entry["action"] == "auth.login" for entry in logs)
    everything = (await client.get("/admin/audit-logs", headers=admin)).text
    assert PASSWORD not in everything and "wrong-password" not in everything


# -------------------------------------------------------------------- doctor
async def test_doctor_sees_and_changes_only_own_appointments(env):
    client, clock, maker, w = env
    mine = await book(maker, w["anil"])
    theirs = await book(maker, w["rahul"], phone="9123456780", start=time(10), name="Ravi Teja")
    doctor = await token(client, "anil")
    page = (await client.get("/doctor/appointments", headers=doctor)).json()
    assert [i["appointment_reference"] for i in page["items"]] == [mine.appointment_reference]
    spoof = await client.get("/doctor/appointments", headers=doctor, params={"doctor_id": str(w["rahul"])})
    assert [i["appointment_reference"] for i in spoof.json()["items"]] == [mine.appointment_reference]
    cancel_theirs = await client.post(f"/doctor/appointments/{theirs.appointment_reference}/cancel", headers=doctor)
    assert cancel_theirs.status_code == 404
    clock.now = datetime(2030, 1, 7, 6, 0, tzinfo=UTC)
    url = f"/doctor/appointments/{theirs.appointment_reference}/status"
    assert (await client.post(url, headers=doctor, json={"status": "COMPLETED"})).status_code == 404
    own = f"/doctor/appointments/{mine.appointment_reference}/status"
    assert (await client.post(own, headers=doctor, json={"status": "NO_SHOW"})).json()["status"] == "NO_SHOW"
    async with maker() as s:
        untouched = await s.scalar(
            select(Appointment).where(Appointment.appointment_reference == theirs.appointment_reference)
        )
        assert untouched.appointment_status.value == "CONFIRMED"


async def test_doctor_cancels_own_and_manages_own_leave(env):
    client, _, maker, w = env
    mine = await book(maker, w["anil"])
    doctor = await token(client, "anil")
    r = await client.post(f"/doctor/appointments/{mine.appointment_reference}/cancel", headers=doctor)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    leave = await client.post(
        "/doctor/leave", headers=doctor, json={"start_date": "2030-01-10", "end_date": "2030-01-11"}
    )
    assert leave.status_code == 201 and leave.json()["doctor_id"] == str(w["anil"])
    assert len((await client.get("/doctor/leave", headers=doctor)).json()) == 1
    other = await token(client, "rahul")
    assert (await client.get("/doctor/leave", headers=other)).json() == []
    assert (await client.delete(f"/doctor/leave/{leave.json()['id']}", headers=other)).status_code == 404
    assert (await client.delete(f"/doctor/leave/{leave.json()['id']}", headers=doctor)).status_code == 204


async def test_cookie_attributes_follow_settings(maker, world):
    """Same-origin proxy mode: path /api/auth, SameSite=Lax; cross-site mode: SameSite=None + Secure."""
    for kwargs, expected in (
        ({"auth_cookie_path": "/api/auth", "auth_cookie_samesite": "lax"}, ("path=/api/auth", "samesite=lax", False)),
        ({"auth_cookie_samesite": "none"}, ("path=/auth", "samesite=none", True)),
    ):
        settings = Settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, **kwargs)
        app = create_app(settings)

        async def _session():
            async with maker() as s:
                yield s

        app.dependency_overrides.update(
            {get_session: _session, get_settings: lambda s=settings: s, get_clock: lambda: Clock()}
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            auth_routes._login_limiter._hits.clear()
            r = await login(c)
            cookie = r.headers["set-cookie"].lower()
            assert expected[0] in cookie and expected[1] in cookie and ("secure" in cookie) is expected[2]
            out = await c.post("/auth/logout", headers=CSRF)
            assert out.status_code == 204 and expected[0] in out.headers["set-cookie"].lower()
