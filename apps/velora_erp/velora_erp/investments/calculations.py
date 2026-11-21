"""Pure investment arithmetic: day counts, income, schedules and accruals. No database, so every rule here is directly testable.

Money is Decimal and rounded half-up to 2 places. A schedule or an accrual always adds back to the exact total (the last period absorbs rounding).
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
BASIS = {"Actual/365": 365, "Actual/360": 360, "30/360": 360}
FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-yearly": 6, "Yearly": 12}
METHODS = ("Simple Interest", "Compound Interest", "Discount (T-Bill)", "Coupon (Bond)", "Flat Rate")

# class -> (asset group, fixed income?, default method, default payment mode, default measurement, default WHT on income?)
CLASSES = {
    "Money Market Placement": ("Money Market", True, "Simple Interest", "At Maturity", "Amortised cost / Cost", True),
    "Treasury Bill": ("Money Market", True, "Discount (T-Bill)", "At Maturity", "Amortised cost / Cost", False),
    "Fixed Deposit": ("Money Market", True, "Simple Interest", "At Maturity", "Amortised cost / Cost", True),
    "Commercial Paper": ("Money Market", True, "Discount (T-Bill)", "At Maturity", "Amortised cost / Cost", True),
    "Bond": ("Capital Market", True, "Coupon (Bond)", "Periodic", "Amortised cost / Cost", True),
    "Equity / Shares": ("Capital Market", False, None, None, "Fair value through profit or loss", True),
    "Mutual Fund / Unit Trust": ("Capital Market", False, None, None, "Fair value through profit or loss", True),
    "Real Estate": ("Real Estate", False, None, None, "Fair value through profit or loss", True),
    "Private Equity": ("Alternative", False, None, None, "Fair value through profit or loss", True),
    "Other": ("Alternative", False, None, None, "Amortised cost / Cost", True),
}


def D(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def money(value) -> Decimal:
    return D(value).quantize(CENT, ROUND_HALF_UP)


def asset_group(investment_class: str) -> str:
    return CLASSES.get(investment_class, CLASSES["Other"])[0]


def is_fixed_income(investment_class: str) -> bool:
    return bool(CLASSES.get(investment_class, CLASSES["Other"])[1])


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def day_count(start: date, end: date, convention: str = "Actual/365") -> int:
    """Days from `start` to `end` under the convention (never negative)."""
    if end <= start:
        return 0
    if convention == "30/360":
        d1 = min(start.day, 30)
        d2 = 30 if (end.day == 31 and d1 == 30) else end.day
        return max(0, (end.year - start.year) * 360 + (end.month - start.month) * 30 + (d2 - d1))
    return (end - start).days


def basis(convention: str) -> int:
    return BASIS.get(convention, 365)


def maturity_from_tenor(start: date, tenor_days: int) -> date:
    return start + timedelta(days=int(tenor_days))


def discount_price(face, discount_rate_percent, days: int, convention: str = "Actual/365") -> Decimal:
    """Price of a discount instrument: face x (1 - d x days / basis)."""
    return money(D(face) * (1 - D(discount_rate_percent) / 100 * D(days) / basis(convention)))


def total_gross_income(method: str, principal, face, rate_percent, days: int, convention: str = "Actual/365") -> Decimal:
    """Gross income over the whole holding period, before tax and fees."""
    p, f, r, b = D(principal), D(face), D(rate_percent) / 100, D(basis(convention))
    if days <= 0:
        return Decimal("0.00")
    if method == "Discount (T-Bill)":
        return money(f - p) if f and p else Decimal("0.00")
    if method == "Compound Interest":
        growth = (1 + float(r)) ** (days / float(b)) - 1
        return money(p * Decimal(str(growth)))
    if method == "Coupon (Bond)":
        return money((f or p) * r * D(days) / b)
    return money(p * r * D(days) / b)            # Simple Interest and Flat Rate


def effective_yield(gross, principal, days: int, convention: str = "Actual/365") -> Decimal:
    """Simple annualised yield on cost, in percent."""
    if D(principal) <= 0 or days <= 0:
        return Decimal("0.00")
    return money(D(gross) / D(principal) * D(basis(convention)) / D(days) * 100)


def _allocate(total: Decimal, weights: list[int]) -> list[Decimal]:
    whole = sum(weights)
    if not whole:
        return [Decimal("0.00")] * len(weights)
    out, running = [], Decimal("0.00")
    for i, w in enumerate(weights):
        part = (total - running) if i == len(weights) - 1 else money(total * w / whole)
        out.append(part)
        running += part
    return out


def build_schedule(start: date, maturity: date, total_gross, mode: str, frequency: str | None = None, wht_rate_percent=0, fee_percent=0, convention: str = "Actual/365") -> list[dict]:
    """The expected cash receipts. At Maturity: one line. Upfront: one line on the start date. Periodic: one line per period, the last ending on maturity."""
    total = money(total_gross)
    if not start or not maturity or maturity <= start:
        return []
    if mode == "Upfront":
        spans = [(start, start, start)]
    elif mode == "Periodic":
        months = FREQUENCY_MONTHS.get(frequency or "", 0)
        if not months:
            return []
        bounds, k = [start], 1
        while True:
            nxt = add_months(start, months * k)
            if nxt >= maturity:
                break
            bounds.append(nxt)
            k += 1
        bounds.append(maturity)
        spans = [(bounds[i], bounds[i + 1], bounds[i + 1]) for i in range(len(bounds) - 1)]
    else:
        spans = [(start, maturity, maturity)]
    weights = [max(1, day_count(a, b, convention)) for a, b, _ in spans] if mode != "Upfront" else [1]
    if mode == "Upfront":                                    # the whole income is received on day one, earned over the tenor
        weights = [1]
    parts = _allocate(total, weights)
    rows = []
    for i, ((a, b, due), gross) in enumerate(zip(spans, parts), 1):
        wht = money(gross * D(wht_rate_percent) / 100)
        fee = money(gross * D(fee_percent) / 100)
        rows.append({"period_no": i, "period_start": a, "period_end": b, "due_date": due, "days": (b - a).days, "gross_interest": gross, "wht_amount": wht, "fee_amount": fee,
                     "net_interest": money(gross - wht - fee), "status": "Scheduled", "received_amount": Decimal("0.00")})
    return rows


def accrued_to(total_gross, start: date, maturity: date, as_of: date, convention: str = "Actual/365") -> Decimal:
    """Straight-line income earned from `start` up to `as_of` (capped at maturity), out of the whole-life income."""
    total = money(total_gross)
    if not start or not maturity or as_of is None or as_of <= start or total <= 0:
        return Decimal("0.00")
    whole = day_count(start, maturity, convention)
    if whole <= 0:
        return Decimal("0.00")
    elapsed = day_count(start, min(as_of, maturity), convention)
    return min(total, money(total * elapsed / whole))


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def apply_receipts(rows: list[dict], received_gross, today: date | None = None) -> list[dict]:
    """Mark schedule lines Received / Part received / Overdue by walking the lines in order against the gross income actually received."""
    left = money(received_gross)
    today = today or date.today()
    for r in rows:
        gross = money(r["gross_interest"])
        take = min(left, gross)
        r["received_amount"] = take
        left -= take
        if gross > 0 and take >= gross:
            r["status"] = "Received"
        elif take > 0:
            r["status"] = "Part received"
        elif r["due_date"] and r["due_date"] < today:
            r["status"] = "Overdue"
        else:
            r["status"] = "Scheduled"
    return rows
