import uuid

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import FieldCipher
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Doctor, DoctorSchedule, Patient
from app.repositories.patients import PatientRepository
from app.services.patients import PatientService


@pytest_asyncio.fixture
async def client(maker):
    async with maker() as s:
        await seed_demo_data(s)
        await s.commit()
    app = create_app(Settings(_env_file=None, app_env="test"))

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_list_specializations_and_doctors(client):
    specs = (await client.get("/specializations")).json()
    assert len(specs) == 5 and specs == sorted(specs, key=lambda x: x["name"])
    docs = (await client.get("/doctors")).json()
    assert len(docs) == 5
    assert all("whatsapp_encrypted" not in d and "is_demo" not in d for d in docs)
    card = next(d for d in docs if d["full_name"] == "Dr. Rahul Reddy")
    assert float(card["consultation_fee"]) == 1000.0
    assert sorted(s["weekday"] for s in card["schedules"]) == [0, 2, 4]


async def test_filter_by_specialization(client):
    spec = next(s for s in (await client.get("/specializations")).json() if s["name"] == "Cardiologist")
    docs = (await client.get("/doctors", params={"specialization_id": spec["id"]})).json()
    assert [d["full_name"] for d in docs] == ["Dr. Rahul Reddy"]


async def test_doctor_detail_404_and_inactive_hidden(client, maker):
    did = (await client.get("/doctors")).json()[0]["id"]
    assert (await client.get(f"/doctors/{did}")).status_code == 200
    assert (await client.get("/doctors/00000000-0000-0000-0000-000000000000")).status_code == 404
    assert (await client.get("/doctors/not-a-uuid")).status_code == 422
    async with maker() as s:
        (await s.get(Doctor, uuid.UUID(did))).is_active = False
        await s.commit()
    assert (await client.get(f"/doctors/{did}")).status_code == 404
    assert len((await client.get("/doctors")).json()) == 4


async def test_inactive_schedule_hidden(client, maker):
    rahul = next(d for d in (await client.get("/doctors")).json() if d["full_name"] == "Dr. Rahul Reddy")
    async with maker() as s:
        stmt = select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == uuid.UUID(rahul["id"]), DoctorSchedule.weekday == 0
        )
        (await s.scalar(stmt)).is_active = False
        await s.commit()
    detail = (await client.get(f"/doctors/{rahul['id']}")).json()
    assert sorted(x["weekday"] for x in detail["schedules"]) == [2, 4]


async def test_patient_service_encrypts_and_dedupes(maker):
    cipher = FieldCipher(Fernet.generate_key().decode(), "hk")
    async with maker() as s:
        svc = PatientService(PatientRepository(s), cipher)
        p = await svc.get_or_create("Asha", "98765 43210", "A@X.com", True)
        await s.commit()
        again = await svc.get_or_create("Asha K", "+919876543210")
        assert again.id == p.id
        with pytest.raises(ValueError):
            await svc.get_or_create("Bad", "123")
    async with maker() as s:
        row = await s.scalar(select(Patient))
        assert "9876543210" not in row.phone_encrypted
        assert PatientService(PatientRepository(s), cipher).phone_of(row) == "+919876543210"
        assert cipher.decrypt(row.email_encrypted) == "a@x.com" and row.notification_consent_at
