import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.database.seed import seed_demo_data
from app.models import Appointment, Doctor, DoctorSchedule, Specialization
from app.models.enums import AppointmentStatus

BASE = datetime(2030, 1, 7, 4, 30, tzinfo=UTC)  # 10:00 IST


def make_appt(doctor_id, start=BASE, minutes=30, status=AppointmentStatus.CONFIRMED, ref=None, **kw):
    end = start + timedelta(minutes=minutes)
    return Appointment(
        appointment_reference=ref or uuid.uuid4().hex[:10].upper(),
        doctor_id=doctor_id,
        patient_name="Test Patient",
        patient_phone_encrypted="enc",
        patient_phone_hash="h" * 64,
        appointment_date=date(2030, 1, 7),
        start_time=time(10),
        end_time=time(10, 30),
        start_at=start,
        end_at=end,
        consultation_fee=Decimal("500"),
        appointment_status=status,
        **kw,
    )


async def new_doctor(maker, name="Dr. T"):
    async with maker() as s:
        spec = Specialization(name=f"S-{uuid.uuid4().hex[:6]}")
        s.add(spec)
        await s.flush()
        doc = Doctor(
            full_name=name, specialization_id=spec.id, experience_years=1, consultation_fee=Decimal("100"), is_demo=True
        )
        s.add(doc)
        await s.commit()
        return doc.id


async def test_seed_creates_demo_data_and_is_idempotent(maker):
    async with maker() as s:
        first = await seed_demo_data(s)
        await s.commit()
    assert first == {"specializations": 5, "doctors": 5, "schedules": 47, "settings": 7}
    async with maker() as s:
        assert await seed_demo_data(s) == {"specializations": 0, "doctors": 0, "schedules": 0, "settings": 0}
        assert await s.scalar(select(func.count()).select_from(Doctor).where(Doctor.is_demo.is_(False))) == 0
        rahul = await s.scalar(select(Doctor).where(Doctor.full_name == "Dr. Rahul Reddy"))
        assert rahul.consultation_fee == Decimal("1000.00")
        assert sorted(x.weekday for x in rahul.schedules) == [0, 2, 4]


async def test_overlapping_appointment_rejected(maker):
    doc = await new_doctor(maker)
    async with maker() as s:
        s.add(make_appt(doc))
        await s.commit()
    async with maker() as s:
        s.add(make_appt(doc, start=BASE + timedelta(minutes=15)))
        with pytest.raises(IntegrityError, match="ex_appointments_no_overlap"):
            await s.commit()


async def test_adjacent_cancelled_and_other_doctor_allowed(maker):
    d1, d2 = await new_doctor(maker, "A"), await new_doctor(maker, "B")
    async with maker() as s:
        s.add(make_appt(d1))
        s.add(make_appt(d1, start=BASE + timedelta(minutes=30)))  # adjacent
        s.add(make_appt(d2))  # other doctor, same time
        s.add(make_appt(d1, status=AppointmentStatus.CANCELLED))  # cancelled does not block
        await s.commit()


async def test_slot_reusable_after_cancellation(maker):
    doc = await new_doctor(maker)
    async with maker() as s:
        a = make_appt(doc)
        s.add(a)
        await s.commit()
        a.appointment_status = AppointmentStatus.CANCELLED
        await s.commit()
        s.add(make_appt(doc))
        await s.commit()


async def _race(maker, doc, n, lock_doctor):
    async def attempt() -> str:
        async with maker() as s:
            try:
                if lock_doctor:  # what BookingService does: serialise per doctor
                    await s.execute(select(Doctor.id).where(Doctor.id == doc).with_for_update())
                s.add(make_appt(doc))
                await s.commit()
                return "won"
            except IntegrityError:
                await s.rollback()
                return "conflict"
            except DBAPIError:  # e.g. deadlock_detected under raw racing
                await s.rollback()
                return "aborted"

    return await asyncio.gather(*(attempt() for _ in range(n)))


async def test_concurrent_raw_race_never_double_books(maker):
    """Constraint alone is safe: one winner, losers get conflict or deadlock-abort."""
    doc = await new_doctor(maker)
    results = await _race(maker, doc, 12, lock_doctor=False)
    assert results.count("won") == 1
    async with maker() as s:
        assert await s.scalar(select(func.count()).select_from(Appointment)) == 1


async def test_concurrent_race_with_doctor_lock_is_clean(maker):
    """With the doctor row lock, losers always get a clean exclusion violation (no deadlocks)."""
    doc = await new_doctor(maker)
    results = await _race(maker, doc, 12, lock_doctor=True)
    assert results.count("won") == 1 and results.count("conflict") == 11


async def test_unique_reference_and_idempotency_key(maker):
    doc = await new_doctor(maker)
    async with maker() as s:
        s.add(make_appt(doc, ref="ABC123", idempotency_key="k1"))
        await s.commit()
    async with maker() as s:
        s.add(make_appt(doc, start=BASE + timedelta(hours=2), ref="ABC123"))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with maker() as s:
        s.add(make_appt(doc, start=BASE + timedelta(hours=3), idempotency_key="k1"))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_check_constraints(maker):
    doc = await new_doctor(maker)
    async with maker() as s:
        s.add(make_appt(doc, minutes=-30))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with maker() as s:
        s.add(DoctorSchedule(doctor_id=doc, weekday=9, session_type="MORNING", start_time=time(9), end_time=time(10)))
        with pytest.raises(IntegrityError):
            await s.commit()
    async with maker() as s:
        s.add(
            DoctorSchedule(
                doctor_id=doc,
                weekday=1,
                session_type="MORNING",
                start_time=time(9),
                end_time=time(12),
                break_start=time(13),
                break_end=time(14),
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
