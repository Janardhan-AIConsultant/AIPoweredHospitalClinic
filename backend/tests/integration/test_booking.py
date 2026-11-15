import asyncio
import re
import uuid
from datetime import UTC, date, datetime, time

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.api.routes.booking import get_cipher, get_clock
from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    SlotUnavailableError,
    ValidationFailure,
)
from app.core.security import FieldCipher
from app.database.seed import seed_demo_data
from app.database.session import get_session
from app.main import create_app
from app.models import Appointment, Doctor, DoctorLeave
from app.models.enums import AppointmentStatus
from app.repositories.booking import BookingRepository
from app.repositories.patients import PatientRepository
from app.services.availability import AvailabilityService
from app.services.booking import BookCommand, BookingService
from app.services.patients import PatientService

DAY = date(2030, 1, 7)  # Monday
NOW = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)
CIPHER = FieldCipher(Fernet.generate_key().decode(), "hash-key")


def clock() -> datetime:
    return NOW


def make_service(session) -> BookingService:
    return BookingService(
        session, BookingRepository(session), PatientService(PatientRepository(session), CIPHER), clock=clock
    )


def cmd(doctor_id, start=time(9), phone="9876543210", key=None, name="Asha Rao", day=DAY) -> BookCommand:
    return BookCommand(
        doctor_id=doctor_id, day=day, start_time=start, patient_name=name, phone=phone, idempotency_key=key
    )


@pytest_asyncio.fixture
async def doc(maker) -> uuid.UUID:
    async with maker() as s:
        await seed_demo_data(s)
        await s.commit()
        return await s.scalar(select(Doctor.id).where(Doctor.full_name == "Dr. Anil Kumar"))


async def count(maker, *where) -> int:
    async with maker() as s:
        return await s.scalar(select(func.count()).select_from(Appointment).where(*where))


async def test_book_success_and_slot_disappears(maker, doc):
    async with maker() as s:
        out = await make_service(s).book(cmd(doc))
    assert out.status == "CONFIRMED" and re.fullmatch(r"\d{8}-\d{4}", out.appointment_reference)
    assert out.doctor_name == "Dr. Anil Kumar" and float(out.consultation_fee) == 500
    async with maker() as s:
        slots = await AvailabilityService(BookingRepository(s), clock=clock).slots_for(doc, DAY)
        assert time(9) not in [x.start_time for x in slots] and time(9, 30) in [x.start_time for x in slots]
        row = await s.scalar(select(Appointment))
        assert "9876543210" not in row.patient_phone_encrypted and row.patient_id is not None
        assert row.start_at == datetime(2030, 1, 7, 3, 30, tzinfo=UTC)


async def test_second_booking_same_slot_rejected(maker, doc):
    async with maker() as s:
        await make_service(s).book(cmd(doc))
    async with maker() as s:
        with pytest.raises(SlotUnavailableError):
            await make_service(s).book(cmd(doc, phone="9123456789"))
    assert await count(maker) == 1


@pytest.mark.parametrize(
    "start,day",
    [(time(9, 10), DAY), (time(13), DAY), (time(14), DAY), (time(9), date(2030, 1, 6)), (time(9), date(2029, 12, 31))],
)
async def test_invalid_slot_rejected(maker, doc, start, day):
    async with maker() as s:
        with pytest.raises(SlotUnavailableError):
            await make_service(s).book(cmd(doc, start=start, day=day))  # off-grid/closed/Sunday/past


async def test_leave_blocks_booking(maker, doc):
    async with maker() as s:
        s.add(DoctorLeave(doctor_id=doc, start_date=DAY, end_date=DAY))
        await s.commit()
    async with maker() as s:
        with pytest.raises(SlotUnavailableError):
            await make_service(s).book(cmd(doc))


async def test_unknown_doctor_and_bad_phone(maker, doc):
    async with maker() as s:
        with pytest.raises(NotFoundError):
            await make_service(s).book(cmd(uuid.uuid4()))
        with pytest.raises(ValidationFailure):
            await make_service(s).book(cmd(doc, phone="123"))


async def test_idempotent_replay_and_mismatch(maker, doc):
    async with maker() as s:
        first = await make_service(s).book(cmd(doc, key="key-12345"))
    async with maker() as s:
        again = await make_service(s).book(cmd(doc, key="key-12345"))
    assert again.appointment_reference == first.appointment_reference and await count(maker) == 1
    async with maker() as s:
        with pytest.raises(ConflictError) as e:
            await make_service(s).book(cmd(doc, start=time(9, 30), key="key-12345"))
    assert e.value.code == "idempotency_conflict"


async def test_concurrent_same_idempotency_key_creates_one(maker, doc):
    async def attempt():
        async with maker() as s:
            return (await make_service(s).book(cmd(doc, key="same-key-1"))).appointment_reference

    refs = await asyncio.gather(*(attempt() for _ in range(6)), return_exceptions=True)
    assert len({r for r in refs if isinstance(r, str)}) == 1
    assert await count(maker) == 1


async def test_concurrent_race_exactly_one_winner_no_errors_leak(maker, doc):
    async def attempt(i: int) -> str:
        async with maker() as s:
            try:
                await make_service(s).book(cmd(doc, phone=f"98765432{i:02d}"))
                return "won"
            except SlotUnavailableError:
                return "unavailable"

    results = await asyncio.gather(*(attempt(i) for i in range(12)))
    assert results.count("won") == 1 and results.count("unavailable") == 11
    assert await count(maker) == 1


async def test_concurrent_same_patient_new_slots_no_duplicate_patient(maker, doc):
    from app.models import Patient

    async def attempt(start):
        async with maker() as s:
            return await make_service(s).book(cmd(doc, start=start))

    slots = [time(9), time(9, 30), time(10), time(10, 30)]
    await asyncio.gather(*(attempt(t) for t in slots))
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(Patient)) == 1
    assert await count(maker) == 4


async def test_cancel_frees_slot_and_blocks_second_cancel(maker, doc):
    async with maker() as s:
        out = await make_service(s).book(cmd(doc))
    async with maker() as s:
        cancelled = await make_service(s).cancel(out.appointment_reference, "changed plans")
    assert cancelled.status == "CANCELLED"
    async with maker() as s:
        with pytest.raises(ConflictError):
            await make_service(s).cancel(out.appointment_reference)
        with pytest.raises(NotFoundError):
            await make_service(s).cancel("NOPE000000")
    async with maker() as s:
        await make_service(s).book(cmd(doc, phone="9123456789"))  # slot reusable


async def test_reschedule_moves_and_links(maker, doc):
    async with maker() as s:
        out = await make_service(s).book(cmd(doc))
    async with maker() as s:
        new = await make_service(s).reschedule(out.appointment_reference, DAY, time(11))
    assert new.start_time == time(11) and new.appointment_reference != out.appointment_reference
    async with maker() as s:
        old = await s.scalar(select(Appointment).where(Appointment.appointment_reference == out.appointment_reference))
        fresh = await s.scalar(
            select(Appointment).where(Appointment.appointment_reference == new.appointment_reference)
        )
        assert old.appointment_status == AppointmentStatus.RESCHEDULED and fresh.rescheduled_from_id == old.id


async def test_reschedule_to_taken_slot_keeps_original(maker, doc):
    async with maker() as s:
        mine = await make_service(s).book(cmd(doc))
        await make_service(s).book(cmd(doc, start=time(10), phone="9123456789"))
    async with maker() as s:
        with pytest.raises(SlotUnavailableError):
            await make_service(s).reschedule(mine.appointment_reference, DAY, time(10))
    async with maker() as s:
        row = await s.scalar(select(Appointment).where(Appointment.appointment_reference == mine.appointment_reference))
        assert row.appointment_status == AppointmentStatus.CONFIRMED


async def test_cannot_cancel_past_appointment(maker, doc):
    async with maker() as s:
        out = await make_service(s).book(cmd(doc))
    async with maker() as s:
        svc = make_service(s)
        svc.clock = lambda: datetime(2030, 1, 7, 6, 0, tzinfo=UTC)
        with pytest.raises(ValidationFailure):
            await svc.cancel(out.appointment_reference)


# ----------------------------------------------------------------- HTTP API
@pytest_asyncio.fixture
async def client(maker, doc):
    app = create_app(Settings(_env_file=None, app_env="test"))

    async def _session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_cipher] = lambda: CIPHER
    app.dependency_overrides[get_clock] = lambda: clock
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def body(doc, **kw):
    base = {
        "doctor_id": str(doc),
        "date": "2030-01-07",
        "start_time": "09:00",
        "patient_name": "Asha Rao",
        "phone": "9876543210",
    }
    return {**base, **kw}


async def test_api_slots_and_booking_flow(client, doc):
    assert (await client.get(f"/doctors/{doc}/slots", params={"date": "not-a-date"})).status_code == 422
    assert (await client.get(f"/doctors/{uuid.uuid4()}/slots", params={"date": "2030-01-07"})).status_code == 404
    far = (await client.get(f"/doctors/{doc}/slots", params={"date": "2031-01-07"})).json()
    assert far["slots"] == []  # beyond booking horizon
    slots = (await client.get(f"/doctors/{doc}/slots", params={"date": "2030-01-07"})).json()["slots"]
    assert slots[0]["start_time"] == "09:00:00" and len(slots) == 14  # 9-13 and 17-20

    r = await client.post("/appointments", json=body(doc), headers={"Idempotency-Key": "api-key-001"})
    assert r.status_code == 201
    data = r.json()
    assert "phone" not in r.text and "9876543210" not in r.text and data["status"] == "CONFIRMED"
    replay = await client.post("/appointments", json=body(doc), headers={"Idempotency-Key": "api-key-001"})
    assert replay.status_code == 201 and replay.json()["appointment_reference"] == data["appointment_reference"]
    clash = await client.post("/appointments", json=body(doc, phone="9123456789"))
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "slot_unavailable"
    after = (await client.get(f"/doctors/{doc}/slots", params={"date": "2030-01-07"})).json()["slots"]
    assert len(after) == 13


async def test_api_validation_errors_do_not_echo_pii(client, doc):
    r = await client.post("/appointments", json=body(doc, phone="12"))
    assert r.status_code == 422 and '"12"' not in r.text
    assert (await client.post("/appointments", json=body(doc, email="bad"))).status_code == 422
    assert (await client.post("/appointments", json=body(doc, patient_name=" "))).status_code == 422
    r = await client.post("/appointments", json=body(doc), headers={"Idempotency-Key": "short"})
    assert r.status_code == 422
    bad = await client.post("/appointments", json=body(doc, phone="12345678"))  # valid length, invalid number
    assert bad.status_code == 422


def test_app_error_hierarchy():
    assert issubclass(SlotUnavailableError, AppError) and SlotUnavailableError.status_code == 409


# ------------------------------------------------------------- reference: <appointment date>-<counter>
async def test_reference_is_date_dash_counter_starting_at_0001_and_counts_per_date(maker, doc):
    async with maker() as s:
        first = await make_service(s).book(cmd(doc, start=time(9)))
    async with maker() as s:
        second = await make_service(s).book(cmd(doc, start=time(9, 30), phone="9876543211"))
    async with maker() as s:
        next_day = await make_service(s).book(cmd(doc, start=time(9), day=date(2030, 1, 8), phone="9876543212"))
    assert first.appointment_reference == "20300107-0001"
    assert second.appointment_reference == "20300107-0002"
    assert next_day.appointment_reference == "20300108-0001"  # each date has its own counter


async def test_cancelled_appointments_keep_their_number_so_a_reference_is_never_reused(maker, doc):
    async with maker() as s:
        a = await make_service(s).book(cmd(doc, start=time(9)))
    async with maker() as s:
        await make_service(s).cancel(a.appointment_reference)
    async with maker() as s:
        b = await make_service(s).book(cmd(doc, start=time(9), phone="9876543211"))
    assert (a.appointment_reference, b.appointment_reference) == ("20300107-0001", "20300107-0002")


async def test_a_rescheduled_appointment_gets_the_next_number_of_its_new_date(maker, doc):
    async with maker() as s:
        out = await make_service(s).book(cmd(doc))
    async with maker() as s:
        new = await make_service(s).reschedule(out.appointment_reference, date(2030, 1, 8), time(10))
    assert out.appointment_reference == "20300107-0001" and new.appointment_reference == "20300108-0001"


async def test_simultaneous_bookings_for_one_date_get_distinct_consecutive_numbers(maker, doc):
    async with maker() as s:
        doctor_ids = list((await s.scalars(select(Doctor.id).order_by(Doctor.full_name))).all())

    async def book(i: int) -> str:
        async with maker() as s:
            doctor = doctor_ids[i % len(doctor_ids)]
            start = time(9) if i < len(doctor_ids) else time(9, 30)
            return (await make_service(s).book(cmd(doctor, start=start, phone=f"98765433{i:02d}"))).appointment_reference

    results = await asyncio.gather(*(book(i) for i in range(8)), return_exceptions=True)
    refs = sorted(r for r in results if isinstance(r, str))
    assert refs, results
    numbers = [int(r.split("-")[1]) for r in refs]
    assert len(set(refs)) == len(refs) and numbers == list(range(1, len(refs) + 1))  # no duplicates, no gaps
