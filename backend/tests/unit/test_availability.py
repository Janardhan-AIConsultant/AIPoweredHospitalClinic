from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.repositories.booking import BookingPolicy
from app.services.availability import generate_slots

MON = date(2030, 1, 7)  # Monday
NOW = datetime(2030, 1, 1, 0, 0, tzinfo=UTC)
POLICY = BookingPolicy(horizon_days=30, min_lead_minutes=60)


@dataclass
class Sched:
    weekday: int = 0
    start_time: time = time(9)
    end_time: time = time(11)
    break_start: time | None = None
    break_end: time | None = None
    is_active: bool = True


def slots(scheds, day=MON, minutes=30, leave=False, booked=(), now=NOW, policy=POLICY):
    return generate_slots(day, scheds, minutes, on_leave=leave, booked=booked, now=now, policy=policy)


def starts(result):
    return [s.start_time for s in result]


def test_basic_grid():
    assert starts(slots([Sched()])) == [time(9), time(9, 30), time(10), time(10, 30)]


def test_partial_trailing_slot_dropped():
    assert starts(slots([Sched(end_time=time(10, 45))])) == [time(9), time(9, 30), time(10)]


def test_wrong_weekday_or_inactive():
    assert slots([Sched(weekday=1)]) == []
    assert slots([Sched(is_active=False)]) == []


def test_break_removes_overlapping_slots():
    result = slots([Sched(end_time=time(12), break_start=time(10), break_end=time(10, 30))])
    assert time(10) not in starts(result) and time(10, 30) in starts(result) and time(9, 30) in starts(result)


def test_two_sessions_merge_sorted():
    result = slots([Sched(start_time=time(16), end_time=time(17)), Sched(start_time=time(9), end_time=time(10))])
    assert starts(result) == [time(9), time(9, 30), time(16), time(16, 30)]


def test_leave_blocks_day():
    assert slots([Sched()], leave=True) == []


def test_booked_interval_removed_and_adjacent_kept():
    nine = slots([Sched()])[0]
    result = slots([Sched()], booked=[(nine.start_at, nine.end_at)])
    assert starts(result) == [time(9, 30), time(10), time(10, 30)]


def test_overlapping_booking_blocks_two_slots():
    nine = slots([Sched()])[0]
    result = slots([Sched()], booked=[(nine.start_at + timedelta(minutes=15), nine.end_at + timedelta(minutes=15))])
    assert time(9) not in starts(result) and time(9, 30) not in starts(result) and time(10) in starts(result)


def test_min_lead_time():
    # 09:00 IST == 03:30 UTC on MON. now = 03:00 UTC, lead 60 -> cutoff 04:00 UTC = 09:30 IST (inclusive).
    now = datetime(2030, 1, 7, 3, 0, tzinfo=UTC)
    assert starts(slots([Sched()], now=now)) == [time(9, 30), time(10), time(10, 30)]


def test_past_day_and_beyond_horizon():
    assert slots([Sched()], now=datetime(2030, 1, 8, tzinfo=UTC)) == []
    assert slots([Sched(weekday=0)], day=date(2030, 2, 11)) == []  # Monday, 41 days out
    assert slots([Sched(weekday=0)], day=date(2030, 1, 28)) != []  # Monday, 27 days out


def test_slot_times_are_utc_converted_from_clinic_time():
    first = slots([Sched()])[0]
    assert first.start_at == datetime(2030, 1, 7, 3, 30, tzinfo=UTC)  # 09:00 IST
    assert first.end_at - first.start_at == timedelta(minutes=30)


def test_custom_slot_length():
    assert starts(slots([Sched()], minutes=60)) == [time(9), time(10)]
