"""Filing and remittance deadlines, penalty exposure and reminders.

Deadlines are made from two numbers in Tax Settings (the day of the following month for WHT and VAT), because the day is set by
the law in force and must not be built in. Exposure is an estimate from the penalty and interest rates entered in Tax Settings;
it is a prompt to act, not an assessment.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from velora import get_list, new_doc
from velora_erp.tax.service import OPEN_STATES, _d, ledger_rows, load_rules, settings

ZERO = Decimal("0")
DAY_SETTING = {"WHT": "wht_remittance_day", "VAT": "vat_filing_day"}


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def _end(start: date) -> date:
    return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def _due(period_end: date, day: int) -> date:
    nxt = period_end + timedelta(days=1)
    return date(nxt.year, nxt.month, min(max(day, 1), calendar.monthrange(nxt.year, nxt.month)[1]))


def ensure_obligations(today: date | None = None, months: int = 3) -> int:
    """Create the monthly WHT and VAT obligations that the ledger shows are needed. Returns how many were made."""
    today = today or date.today()
    st = settings()
    kinds = {t: int(st[k]) for t, k in DAY_SETTING.items() if st.get(k) not in (None, "", 0)}
    if not kinds:
        return 0
    meta = {r.code: (r.tax_type, r.jurisdiction) for r in load_rules(None)}
    made = 0
    for back in range(1, months + 1):
        start = _month_start(today, back)
        end = _end(start)
        seen = {m for r in ledger_rows(start, end) if (m := meta.get((r["tax_code"] or "").upper())) and m[0] in kinds}
        for tax_type, jur in sorted(seen):
            if get_list("Tax Obligation", filters=[["tax_type", "=", tax_type], ["jurisdiction", "=", jur], ["period_start", "=", start]], fields=["name"], limit=1, ignore_permissions=True):
                continue
            new_doc("Tax Obligation", tax_type=tax_type, jurisdiction=jur, period_start=start, period_end=end, due_date=_due(end, kinds[tax_type]),
                    notes="Created automatically from the tax ledger and the day set in Tax Settings.").insert(ignore_permissions=True)
            made += 1
    return made


def _as_date(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def exposure(obligation: dict, today: date | None = None) -> dict:
    """Estimated penalty and interest on an overdue obligation, from the rates in Tax Settings."""
    today = today or date.today()
    st = settings()
    due = _as_date(obligation["due_date"])
    if due >= today:
        return {"days_late": 0, "tax": ZERO, "penalty": ZERO, "interest": ZERO, "total": ZERO}
    meta = {r.code: (r.tax_type, r.jurisdiction) for r in load_rules(None)}
    tax = ZERO
    for r in ledger_rows(_as_date(obligation["period_start"]), _as_date(obligation["period_end"])):
        if meta.get((r["tax_code"] or "").upper()) == (obligation["tax_type"], obligation["jurisdiction"]):
            if r["section"] == "Output tax":
                tax += r["tax"]
            elif obligation["tax_type"] != "WHT":      # VAT input tax is set off; WHT credits suffered are not set against WHT you must remit
                tax -= r["tax"]
    tax = max(tax, ZERO)
    days = (today - due).days
    months_late = -(-days // 30)
    penalty = _d(st.get("late_penalty_flat")) + tax * _d(st.get("late_penalty_monthly_percent")) / 100 * max(months_late - 1, 0)
    interest = tax * _d(st.get("late_interest_annual_percent")) / 100 * days / 365
    q = Decimal("0.01")
    return {"days_late": days, "tax": tax.quantize(q), "penalty": penalty.quantize(q), "interest": interest.quantize(q), "total": (tax + penalty + interest).quantize(q)}


def remind(today: date | None = None) -> int:
    """Send due-soon and overdue reminders through the notification rules (events tax_obligation_due_soon / tax_obligation_overdue)."""
    try:
        from velora_notify import engine
    except Exception:  # noqa: BLE001 - notifications are optional
        return 0
    from velora import get_doc
    today = today or date.today()
    window = int(settings().get("filing_reminder_days") or 7)
    sent = 0
    for o in get_list("Tax Obligation", filters=[["status", "in", list(OPEN_STATES)]], fields=["name", "due_date"], limit=100000, ignore_permissions=True):
        left = (_as_date(o["due_date"]) - today).days
        if left < 0 and today.weekday() == 0:
            event, key = "tax_obligation_overdue", f"{o['name']}:overdue:{today.isocalendar()[0]}-{today.isocalendar()[1]}"
        elif left in {window, 3, 1, 0}:
            event, key = "tax_obligation_due_soon", f"{o['name']}:due:{left}"
        else:
            continue
        try:
            sent += engine.trigger(event, get_doc("Tax Obligation", o["name"], ignore_permissions=True), key=key) or 0
        except Exception:  # noqa: BLE001 - a failed message must never stop the daily job
            pass
    return sent
