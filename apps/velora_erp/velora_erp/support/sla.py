"""Working-hours arithmetic for service levels. Pure functions: no database, no clock.

All datetimes are naive UTC (the framework convention). A calendar converts them to the team's local
time, so "08:00 to 17:00 Monday to Friday" means the team's own day, whatever the server clock says.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def parse_hhmm(value, default: str) -> time:
    text = (value or default or "").strip()
    try:
        hour, minute = text.split(":")
        return time(int(hour), int(minute))
    except Exception:  # noqa: BLE001
        h, m = default.split(":")
        return time(int(h), int(m))


@dataclass
class Calendar:
    round_the_clock: bool = False
    start: time = time(8, 0)
    end: time = time(17, 0)
    days: frozenset = field(default_factory=lambda: frozenset({0, 1, 2, 3, 4}))
    holidays: frozenset = field(default_factory=frozenset)
    utc_offset: float = 1.0

    def local(self, utc: datetime) -> datetime:
        return utc + timedelta(hours=self.utc_offset)

    def to_utc(self, local: datetime) -> datetime:
        return local - timedelta(hours=self.utc_offset)

    def working(self, day: date) -> bool:
        return self.round_the_clock or (day.weekday() in self.days and day not in self.holidays)

    def window(self, day: date):
        """Local (start, end) of working time on `day`, or None."""
        if not self.working(day):
            return None
        if self.round_the_clock:
            return datetime.combine(day, time(0, 0)), datetime.combine(day + timedelta(days=1), time(0, 0))
        s, e = datetime.combine(day, self.start), datetime.combine(day, self.end)
        return (s, e) if e > s else None

    def usable(self) -> bool:
        if self.round_the_clock:
            return True
        return bool(self.days) and self.end > self.start


def calendar_from(sla: dict, holidays=()) -> Calendar:
    days = frozenset(i for i, d in enumerate(WEEKDAYS) if int(sla.get(d) or 0))
    return Calendar(
        round_the_clock=bool(int(sla.get("round_the_clock") or 0)),
        start=parse_hhmm(sla.get("work_start"), "08:00"),
        end=parse_hhmm(sla.get("work_end"), "17:00"),
        days=days,
        holidays=frozenset(holidays),
        utc_offset=float(sla.get("utc_offset_hours") if sla.get("utc_offset_hours") is not None else 1.0),
    )


def add_working_seconds(cal: Calendar, start: datetime, seconds: float) -> datetime:
    """The moment `seconds` of working time after `start` (naive UTC in, naive UTC out)."""
    if seconds <= 0:
        return start
    if not cal.usable():
        return start + timedelta(seconds=seconds)
    cur = cal.local(start)
    remaining = float(seconds)
    for _ in range(366 * 3):                       # a hard stop: three years of days is more than any target
        win = cal.window(cur.date())
        if win:
            lo, hi = max(cur, win[0]), win[1]
            if hi > lo:
                available = (hi - lo).total_seconds()
                if remaining <= available:
                    return cal.to_utc(lo + timedelta(seconds=remaining))
                remaining -= available
        cur = datetime.combine(cur.date() + timedelta(days=1), time(0, 0))
    return cal.to_utc(cur)


def working_seconds_between(cal: Calendar, start: datetime, end: datetime) -> float:
    """Working time that elapsed between two naive UTC moments."""
    if end <= start:
        return 0.0
    if not cal.usable():
        return (end - start).total_seconds()
    a, b = cal.local(start), cal.local(end)
    total = 0.0
    day = a.date()
    while day <= b.date():
        win = cal.window(day)
        if win:
            lo, hi = max(a, win[0]), min(b, win[1])
            if hi > lo:
                total += (hi - lo).total_seconds()
        day += timedelta(days=1)
    return total


def state(cal: Calendar, started: datetime, due: datetime, now: datetime, warn_percent: float) -> str:
    """On track / At risk / Breached for a running clock."""
    if now >= due:
        return "Breached"
    total = working_seconds_between(cal, started, due)
    if total <= 0:
        return "On track"
    used = working_seconds_between(cal, started, now)
    return "At risk" if used / total * 100 >= float(warn_percent or 80) else "On track"
