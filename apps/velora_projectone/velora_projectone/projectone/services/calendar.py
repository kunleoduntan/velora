"""Project working-calendar calculations using ISO dates and explicit holidays."""
from datetime import date, timedelta


def _date(value):
    try: return date.fromisoformat(str(value))
    except (TypeError, ValueError): raise ValueError("Dates must use ISO YYYY-MM-DD format.")


def is_working_day(day, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
    return day.weekday() in set(working_weekdays) and day.isoformat() not in set(holidays)


def add_working_days(start_date, days, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
    current = _date(start_date)
    if not isinstance(days, int): raise ValueError("days must be an integer.")
    if days == 0: return current.isoformat()
    step = 1 if days > 0 else -1
    remaining = abs(days)
    while remaining:
        current += timedelta(days=step)
        if is_working_day(current, working_weekdays, holidays): remaining -= 1
    return current.isoformat()


def working_days_between(start_date, end_date, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
    start, end = _date(start_date), _date(end_date)
    if end < start: raise ValueError("End date cannot be earlier than start date.")
    count, current = 0, start
    while current <= end:
        if is_working_day(current, working_weekdays, holidays): count += 1
        current += timedelta(days=1)
    return count
