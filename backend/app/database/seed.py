"""Idempotent demo-data seeder. All doctors/schedules are flagged ``is_demo=True``.

Run: ``python -m app.database.seed``. Doctor WhatsApp numbers are intentionally left
empty (set them via the admin UI); no real contact data is seeded.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClinicSetting, Doctor, DoctorSchedule, Specialization
from app.models.enums import SessionType

logger = logging.getLogger(__name__)

MON, TUE, WED, THU, FRI, SAT = range(6)


@dataclass(frozen=True)
class DemoDoctor:
    name: str
    specialization: str
    experience: int
    fee: str
    days: tuple[int, ...]
    morning: tuple[time, time] | None
    evening: tuple[time, time] | None
    qualifications: str


DEMO_DOCTORS: tuple[DemoDoctor, ...] = (
    DemoDoctor(
        "Dr. Anil Kumar",
        "General Physician",
        12,
        "500",
        tuple(range(MON, SAT + 1)),
        (time(9), time(13)),
        (time(17), time(20)),
        "MBBS, MD (General Medicine) [demo]",
    ),
    DemoDoctor(
        "Dr. Priya Sharma",
        "Pediatrician",
        10,
        "600",
        tuple(range(MON, FRI + 1)),
        (time(10), time(13)),
        (time(16), time(19)),
        "MBBS, MD (Pediatrics) [demo]",
    ),
    DemoDoctor(
        "Dr. Rahul Reddy",
        "Cardiologist",
        15,
        "1000",
        (MON, WED, FRI),
        (time(9), time(12)),
        None,
        "MBBS, MD, DM (Cardiology) [demo]",
    ),
    DemoDoctor(
        "Dr. Sneha Rao",
        "Dermatologist",
        8,
        "700",
        tuple(range(TUE, SAT + 1)),
        (time(10), time(13)),
        (time(17), time(19)),
        "MBBS, MD (Dermatology) [demo]",
    ),
    DemoDoctor(
        "Dr. Vikram Raju",
        "Orthopedic Specialist",
        14,
        "800",
        tuple(range(MON, SAT + 1)),
        (time(9), time(12)),
        (time(16), time(18)),
        "MBBS, MS (Orthopedics) [demo]",
    ),
)

DEFAULT_SETTINGS: dict[str, tuple[object, str]] = {
    "clinic_name": ("Bindu Clinic", "Display name"),
    "timezone": ("Asia/Kolkata", "Clinic timezone (IANA)"),
    "default_slot_minutes": (30, "Default appointment duration"),
    "booking_horizon_days": (30, "How far ahead patients can book"),
    "min_lead_minutes": (60, "Minimum notice before a slot can be booked"),
    "emergency_number": ("112", "Shown by the chatbot on emergencies (India)"),
    "arrival_instruction_minutes": (10, "Arrive this many minutes early"),
}


async def seed_demo_data(session: AsyncSession) -> dict[str, int]:
    """Insert missing demo rows; safe to run repeatedly. Caller commits."""
    created = {"specializations": 0, "doctors": 0, "schedules": 0, "settings": 0}

    for key, (value, description) in DEFAULT_SETTINGS.items():
        if not await session.scalar(select(ClinicSetting.id).where(ClinicSetting.key == key)):
            session.add(ClinicSetting(key=key, value=value, description=description))
            created["settings"] += 1

    for demo in DEMO_DOCTORS:
        spec = await session.scalar(select(Specialization).where(Specialization.name == demo.specialization))
        if spec is None:
            spec = Specialization(name=demo.specialization)
            session.add(spec)
            await session.flush()
            created["specializations"] += 1

        doctor = await session.scalar(select(Doctor).where(Doctor.full_name == demo.name, Doctor.is_demo.is_(True)))
        if doctor is None:
            doctor = Doctor(
                full_name=demo.name,
                specialization_id=spec.id,
                experience_years=demo.experience,
                consultation_fee=Decimal(demo.fee),
                qualifications=demo.qualifications,
                slot_minutes=30,
                is_demo=True,
            )
            session.add(doctor)
            await session.flush()
            created["doctors"] += 1

        existing = {
            (s.weekday, s.session_type)
            for s in (await session.scalars(select(DoctorSchedule).where(DoctorSchedule.doctor_id == doctor.id)))
        }
        for weekday in demo.days:
            for kind, window in ((SessionType.MORNING, demo.morning), (SessionType.EVENING, demo.evening)):
                if window and (weekday, kind) not in existing:
                    session.add(
                        DoctorSchedule(
                            doctor_id=doctor.id,
                            weekday=weekday,
                            session_type=kind,
                            start_time=window[0],
                            end_time=window[1],
                            is_demo=True,
                        )
                    )
                    created["schedules"] += 1
    await session.flush()
    return created


async def _main() -> None:
    from app.database.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        result = await seed_demo_data(session)
        await session.commit()
    logger.info("seed_complete", extra={"operation": "seed", **result})
    print("Seed result:", result)


if __name__ == "__main__":
    asyncio.run(_main())
