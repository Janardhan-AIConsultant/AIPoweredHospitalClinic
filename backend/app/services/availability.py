"""Availability engine.

``generate_slots`` is a pure function (no I/O, injectable clock) so every rule is
unit-testable. ``AvailabilityService`` loads the inputs and calls it. The booking
service re-runs the same function under a row lock, so what is shown to patients
and what is enforced at write time can never diverge.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Protocol

from app.core.exceptions import NotFoundError
from app.models import Doctor
from app.repositories.booking import BookingPolicy, BookingRepository
from app.utils.timezone import clinic_tz, to_utc, utcnow


@dataclass(frozen=True)
class Slot:
    start_time: time
    end_time: time
    start_at: datetime  # UTC
    end_at: datetime  # UTC


class ScheduleLike(Protocol):
    weekday: int
    start_time: time
    end_time: time
    break_start: time | None
    break_end: time | None
    is_active: bool


def _add(t: time, minutes: int) -> datetime:
    return datetime.combine(date(2000, 1, 1), t) + timedelta(minutes=minutes)


def generate_slots(
    day: date,
    schedules: Iterable[ScheduleLike],
    slot_minutes: int,
    *,
    on_leave: bool,
    booked: Iterable[tuple[datetime, datetime]],
    now: datetime,
    policy: BookingPolicy,
) -> list[Slot]:
    """Return bookable slots for one doctor on one clinic-local day, sorted by start."""
    if on_leave:
        return []
    today = now.astimezone(clinic_tz()).date()
    if day < today or day > today + timedelta(days=policy.horizon_days):
        return []

    earliest = now + timedelta(minutes=policy.min_lead_minutes)
    booked_list = list(booked)
    slots: dict[time, Slot] = {}
    for sched in schedules:
        if not sched.is_active or sched.weekday != day.weekday():
            continue
        end_limit = datetime.combine(date(2000, 1, 1), sched.end_time)
        cursor = datetime.combine(date(2000, 1, 1), sched.start_time)
        while cursor + timedelta(minutes=slot_minutes) <= end_limit:
            start_t, end_t = cursor.time(), (cursor + timedelta(minutes=slot_minutes)).time()
            cursor += timedelta(minutes=slot_minutes)
            if sched.break_start and sched.break_end and start_t < sched.break_end and end_t > sched.break_start:
                continue
            start_at, end_at = to_utc(day, start_t), to_utc(day, end_t)
            if start_at < earliest:
                continue
            if any(start_at < b_end and end_at > b_start for b_start, b_end in booked_list):
                continue
            slots.setdefault(start_t, Slot(start_t, end_t, start_at, end_at))
    return [slots[k] for k in sorted(slots)]


class AvailabilityService:
    def __init__(self, repo: BookingRepository, clock: Callable[[], datetime] = utcnow) -> None:
        self.repo = repo
        self.clock = clock

    async def slots_for(self, doctor_id: uuid.UUID, day: date) -> list[Slot]:
        doctor = await self.repo.get_doctor(doctor_id)
        if doctor is None:
            raise NotFoundError("Doctor not found.")
        return await compute_slots(self.repo, doctor, day, self.clock())


async def compute_slots(repo: BookingRepository, doctor: Doctor, day: date, now: datetime) -> list[Slot]:
    policy = await repo.get_policy()
    return generate_slots(
        day,
        doctor.schedules,
        doctor.slot_minutes,
        on_leave=await repo.on_leave(doctor.id, day),
        booked=await repo.active_intervals(doctor.id, day),
        now=now,
        policy=policy,
    )
