"""Treasury data logic: positions are always recomputed from the submitted documents, so cancelling or amending anything keeps every balance honest."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from velora import db, get_doc, get_list
from velora.db.tables import get_table
from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.treasury import engine as eng

ZERO = Decimal("0")
DEFAULTS = {"repayment_warning_days": 7, "expiry_warning_days": 90, "utilisation_alert_percent": 85, "lender_concentration_percent": 60, "fx_shock_percent": 10,
            "rate_shock_points": 1, "forecast_weeks": 13, "minimum_cash_buffer": 0, "default_interest_wht_rule": None}


def D(v):
    return Decimal(str(v if v not in (None, "") else 0))


def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10]) if v else None


def settings() -> dict:
    out = dict(DEFAULTS)
    rows = get_list("Treasury Settings", fields=list(DEFAULTS), limit=1, ignore_permissions=True)
    if rows:
        out.update({k: v for k, v in rows[0].items() if v is not None and v != ""})
    return out


def base_currency() -> str:
    from velora_erp.finance.source_documents import finance_settings
    return finance_settings()["base_currency"]


def rate_for(currency, on=None):
    """Latest recorded rate to the base currency on or before `on`; 1 for the base currency; None when no rate is recorded."""
    base = base_currency()
    if (currency or base).upper() == base:
        return Decimal(1)
    rows = get_list("Currency Exchange Rate", filters=[["from_currency", "=", currency], ["to_currency", "=", base], ["effective_date", "<=", on or date.today()]],
                    fields=["rate", "effective_date"], order_by="effective_date desc", limit=1, ignore_permissions=True)
    return D(rows[0]["rate"]) if rows else None


def submitted(doctype, filters=None, fields=("name",), order=None, limit=5000):
    return get_list(doctype, filters=[["docstatus", "=", 1]] + list(filters or []), fields=list(fields), order_by=order, limit=limit, ignore_permissions=True)


# ------------------------------------------------------------------ rates and schedules
def rate_timeline(dd) -> list:
    """[(effective_from, rate)] for a drawdown: its own rate, then (floating loans only) the facility's amended rates."""
    g = (lambda k: dd.get(k)) if isinstance(dd, dict) else (lambda k: getattr(dd, k, None))
    start = as_date(g("drawdown_date"))
    timeline = [(start, D(g("interest_rate")))]
    if g("interest_rate_type") == "Floating":
        for a in submitted("Facility Amendment", [["facility", "=", g("facility")]], ["effective_date", "new_interest_rate"], "effective_date asc"):
            if a["new_interest_rate"] and as_date(a["effective_date"]) > start:
                timeline.append((as_date(a["effective_date"]), D(a["new_interest_rate"])))
    return timeline


def schedule_rows(dd) -> list[dict]:
    g = (lambda k: dd.get(k)) if isinstance(dd, dict) else (lambda k: getattr(dd, k, None))
    rows = eng.schedule(D(g("amount")), as_date(g("drawdown_date")), eng.rate_function(rate_timeline(dd)), structure=g("repayment_structure"), frequency=g("repayment_frequency"),
                        tenor_months=int(g("tenor_months") or 0), grace_months=int(g("grace_period_months") or 0), basis=g("day_count_basis") or "Actual/365")
    return [{"number": r["number"], "due_date": r["due_date"], "opening_principal": r["opening"], "principal_due": r["principal"], "interest_due": r["interest"],
             "total_due": r["total"], "closing_principal": r["closing"], "principal_paid": 0, "interest_paid": 0, "status": "Scheduled"} for r in rows]


def _lines(drawdown):
    t = get_table("Repayment Schedule Line")
    with db.transaction() as c:
        return [dict(r) for r in c.execute(select(t).where(t.c.parent == drawdown).order_by(t.c.idx)).mappings()]


def replace_schedule(dd, rows):
    """Replace a submitted drawdown's schedule rows (a rate change reprices the instalments that have not fallen due)."""
    from sqlalchemy import delete, insert
    from velora import naming
    from velora.meta.registry import registry
    meta = registry.get("Repayment Schedule Line")
    t = get_table("Repayment Schedule Line")
    with db.transaction() as c:
        c.execute(delete(t).where(t.c.parent == dd.name, t.c.parenttype == "Financing Drawdown", t.c.parentfield == "schedule"))
        for i, r in enumerate(rows, 1):
            ch = registry.controller_for(meta.name)(meta, dict(r))
            ch.parent, ch.parenttype, ch.parentfield, ch.idx = dd.name, "Financing Drawdown", "schedule", i
            ch.owner, ch.creation, ch.modified, ch.modified_by, ch.docstatus = dd.owner, dd.creation, dd.modified, dd.modified_by, 1
            ch.name = naming.make_name(meta, ch)
            c.execute(insert(t).values(**{k: getattr(ch, k, None) for k in t.c.keys()}))


def reprice(facility):
    """Rebuild the schedules of the facility's active floating-rate loans after a rate amendment, then replay the payments made."""
    for r in submitted("Financing Drawdown", [["facility", "=", facility], ["interest_rate_type", "=", "Floating"], ["status", "=", "Active"]], ["name"]):
        dd = get_doc("Financing Drawdown", r["name"], ignore_permissions=True)
        replace_schedule(dd, schedule_rows(dd))
        refresh_drawdown(dd.name)


# ------------------------------------------------------------------ refresh (recompute from source documents)
def refresh_drawdown(name):
    dd = get_doc("Financing Drawdown", name, ignore_permissions=True)
    if dd.docstatus != 1:
        return None
    reps = submitted("Financing Repayment", [["drawdown", "=", name]], ["repayment_date", "principal_amount", "interest_amount", "accrued_interest_cleared"], "repayment_date asc")
    ac, al = get_table("Interest Accrual"), get_table("Interest Accrual Line")
    with db.transaction() as c:
        accr = [dict(r) for r in c.execute(select(al.c.interest, al.c.to_date).join(ac, ac.c.name == al.c.parent).where(al.c.drawdown == name, ac.c.docstatus == 1)).mappings()]
    principal = sum((D(r["principal_amount"]) for r in reps), ZERO)
    interest = sum((D(r["interest_amount"]) for r in reps), ZERO)
    cleared = sum((D(r["accrued_interest_cleared"]) for r in reps), ZERO)
    accrued = sum((D(r["interest"]) for r in accr), ZERO)
    accrued_to = max([as_date(r["to_date"]) for r in accr], default=as_date(dd.drawdown_date))
    outstanding = D(dd.amount) - principal
    lines = _lines(name)
    paid = eng.allocate(lines, [(as_date(r["repayment_date"]), r["principal_amount"], r["interest_amount"]) for r in reps])
    for line, (pp, ip) in zip(lines, paid):
        full = pp >= D(line["principal_due"]) and ip >= D(line["interest_due"])
        status = "Paid" if full else ("Part paid" if (pp > 0 or ip > 0) else "Scheduled")
        if (D(line["principal_paid"]), D(line["interest_paid"]), line["status"]) != (pp, ip, status):
            db_update_child("Repayment Schedule Line", line["name"], principal_paid=pp, interest_paid=ip, status=status)
    db_update(dd, outstanding_principal=outstanding, principal_repaid=principal, interest_paid=interest, accrued_interest_balance=accrued - cleared,
              interest_accrued_to=accrued_to, status="Repaid" if outstanding <= 0 else "Active")
    return dd


def refresh_facility(name):
    fac = get_doc("Financing Facility", name, ignore_permissions=True)
    if fac.docstatus != 1:
        return None
    dds = submitted("Financing Drawdown", [["facility", "=", name]], ["name", "amount", "outstanding_principal", "principal_repaid", "accrued_interest_balance"])
    drawn = sum((D(r["amount"]) for r in dds), ZERO)
    repaid = sum((D(r["principal_repaid"]) for r in dds), ZERO)
    out = sum((D(r["outstanding_principal"]) for r in dds), ZERO)
    acc = sum((D(r["accrued_interest_balance"]) for r in dds), ZERO)
    limit = D(fac.approved_limit)
    used = out if fac.allows_redraw else drawn
    status = "Active" if as_date(fac.expiry_date) >= date.today() else ("Closed" if out <= 0 else "Expired")
    db_update(fac, total_drawn=drawn, principal_repaid=repaid, outstanding_principal=out, undrawn_available=max(ZERO, limit - used),
              utilisation_percent=(used / limit * 100).quantize(Decimal("0.01")) if limit > 0 else 0, accrued_interest_balance=acc, status=status)
    return fac


def facility_available(fac) -> Decimal:
    limit = D(fac.approved_limit)
    used = D(fac.outstanding_principal) if fac.allows_redraw else D(fac.total_drawn)
    return max(ZERO, limit - used)


# ------------------------------------------------------------------ interest accrual
def accrual_lines(currency, through: date, facility=None) -> list[dict]:
    """Interest owed since each active loan was last accrued, through `through` (inclusive)."""
    to = through + timedelta(days=1)
    flt = [["currency", "=", currency], ["status", "=", "Active"]] + ([["facility", "=", facility]] if facility else [])
    out = []
    for r in submitted("Financing Drawdown", flt, ["name", "facility", "drawdown_date", "amount", "interest_rate", "interest_rate_type", "day_count_basis", "interest_accrued_to"]):
        frm = as_date(r["interest_accrued_to"]) or as_date(r["drawdown_date"])
        reps = [(as_date(x["repayment_date"]), D(x["principal_amount"])) for x in submitted("Financing Repayment", [["drawdown", "=", r["name"]]], ["repayment_date", "principal_amount"])]
        for seg in eng.accrue(D(r["amount"]), as_date(r["drawdown_date"]), frm, to, reps, eng.rate_function(rate_timeline(r)), r["day_count_basis"] or "Actual/365"):
            if seg["interest"] > 0:
                out.append({"drawdown": r["name"], "facility": r["facility"], "from_date": seg["from_date"], "to_date": seg["to_date"], "days": seg["days"],
                            "principal_balance": seg["balance"], "rate": seg["rate"], "interest": seg["interest"]})
    return out
