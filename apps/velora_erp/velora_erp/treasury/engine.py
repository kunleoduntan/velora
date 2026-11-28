"""Treasury arithmetic with no database: day counts, repayment schedules and interest accrual.

Everything is Decimal. A schedule can be rebuilt at any time from the drawdown's terms and the rate history, so repricing a floating
facility never needs hand-edited rows.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

ZERO = Decimal("0")
CENT = Decimal("0.01")
MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-yearly": 6, "Annual": 12}
STRUCTURES = ("Annuity", "Equal principal", "Interest only, principal at maturity", "Bullet (principal and interest at maturity)")
BASES = ("Actual/365", "Actual/360", "30/360")


def D(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def money(v) -> Decimal:
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def days_between(a: date, b: date, basis: str = "Actual/365") -> int:
    if basis == "30/360":
        d1, d2 = min(a.day, 30), b.day if a.day < 30 else min(b.day, 30)
        return 360 * (b.year - a.year) + 30 * (b.month - a.month) + (d2 - d1)
    return (b - a).days


def year_days(basis: str) -> int:
    return 365 if basis == "Actual/365" else 360


def interest(balance, rate_pct, a: date, b: date, basis: str = "Actual/365") -> Decimal:
    """Interest on `balance` at an annual percentage rate from a (inclusive) to b (exclusive)."""
    if b <= a:
        return ZERO
    return D(balance) * D(rate_pct) / Decimal(100) * Decimal(days_between(a, b, basis)) / Decimal(year_days(basis))


def schedule(principal, start: date, rate_at, *, structure="Annuity", frequency="Monthly", tenor_months=12, grace_months=0, basis="Actual/365") -> list[dict]:
    """Instalments for a loan drawn on `start`. `rate_at(date)` gives the annual rate in force on a date (use a constant lambda for fixed loans).

    Each row: number, due_date, opening, principal, interest, total, closing. The last row clears the balance exactly.
    """
    p = D(principal)
    step = MONTHS[frequency]
    if p <= 0:
        raise ValueError("The amount must be greater than zero.")
    if structure not in STRUCTURES:
        raise ValueError(f"Unknown repayment structure {structure}.")
    if int(tenor_months) < step:
        raise ValueError("The tenor must cover at least one repayment period.")
    n = -(-int(tenor_months) // step)                       # whole periods, rounded up
    grace = min(n - 1, int(grace_months) // step) if structure in ("Annuity", "Equal principal") else 0
    rows, balance, prev = [], p, start
    for i in range(1, n + 1):
        due = start + relativedelta(months=step * i)
        rate = D(rate_at(prev))
        accrued = money(interest(balance, rate, prev, due, basis))
        left = n - i + 1                                     # periods still to pay, including this one
        if structure == "Bullet (principal and interest at maturity)":
            owed_p = balance if i == n else ZERO
            accrued = money(interest(p, rate, start, due, basis)) if i == n else ZERO   # simple interest for the whole term at the rate in force
            if i == n:
                accrued = money(sum((interest(p, rate_at(start + relativedelta(months=step * (j - 1))), start + relativedelta(months=step * (j - 1)), start + relativedelta(months=step * j), basis) for j in range(1, n + 1)), ZERO))
        elif structure == "Interest only, principal at maturity":
            owed_p = balance if i == n else ZERO
        elif i <= grace:
            owed_p = ZERO
        elif structure == "Equal principal":
            owed_p = money(balance / Decimal(n - grace - (i - grace - 1))) if i < n else balance
        else:                                                # annuity: recompute the level payment on the balance and the periods left, at today's rate
            periods_left = left
            r = rate / Decimal(100) * Decimal(step) / Decimal(12)
            if i == n:
                owed_p = balance
            else:
                level = money(balance / Decimal(periods_left)) if r == 0 else money(balance * r / (1 - (1 + r) ** (-periods_left)))
                owed_p = min(balance, max(ZERO, level - accrued))
        owed_p = min(money(owed_p), balance)
        closing = money(balance - owed_p)
        rows.append({"number": i, "due_date": due, "opening": money(balance), "principal": owed_p, "interest": accrued, "total": money(owed_p + accrued), "closing": closing})
        balance, prev = closing, due
    return rows


def rate_lookup(timeline):
    """timeline: [(effective_from, rate)] -> function(date) giving the rate in force."""
    ordered = sorted(timeline, key=lambda x: x[0])

    def at(d: date):
        rate = ordered[0][1]
        for eff, r in ordered:
            if eff <= d:
                rate = r
            else:
                break
        return D(rate)
    return at


def accrue(opening_principal, drawdown_date: date, frm: date, to: date, repayments, rate_at, basis="Actual/365") -> list[dict]:
    """Interest from `frm` to `to` (days frm..to-1) on the principal outstanding each day.

    repayments: [(date, principal_repaid)]: principal falls on that date. The rate may change inside the period; one row per stretch.
    """
    if to <= frm:
        return []
    cuts = {frm, to}
    reps = sorted((d, D(a)) for d, a in repayments if D(a) > 0)
    cuts |= {d for d, _ in reps if frm < d < to}
    cuts |= {d for d in getattr(rate_at, "dates", []) if frm < d < to}
    pts = sorted(cuts)
    rows = []
    for a, b in zip(pts, pts[1:]):
        balance = D(opening_principal) - sum((x for d, x in reps if d <= a), ZERO)
        if balance <= 0:
            continue
        rate = rate_at(a)
        rows.append({"from_date": a, "to_date": b, "days": days_between(a, b, basis), "balance": money(balance), "rate": rate, "interest": money(interest(balance, rate, a, b, basis))})
    return rows


def rate_function(timeline):
    f = rate_lookup(timeline)
    f.dates = [d for d, _ in timeline]
    return f


def allocate(lines, repayments):
    """Replay repayments (date order) against schedule lines (principal and interest separately, oldest first).

    lines: [{'principal_due','interest_due', ...}] in order; repayments: [(date, principal, interest)]. Returns [(principal_paid, interest_paid)].
    """
    paid = [[ZERO, ZERO] for _ in lines]
    for _, p, i in sorted(repayments, key=lambda x: x[0]):
        p, i = D(p), D(i)
        for k, line in enumerate(lines):
            if p > 0:
                room = D(line["principal_due"]) - paid[k][0]
                take = min(room, p) if room > 0 else ZERO
                paid[k][0] += take; p -= take
            if i > 0:
                room = D(line["interest_due"]) - paid[k][1]
                take = min(room, i) if room > 0 else ZERO
                paid[k][1] += take; i -= take
    return [tuple(x) for x in paid]
