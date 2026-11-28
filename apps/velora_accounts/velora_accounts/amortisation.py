"""Amortisation: spread a prepaid cost over several months without posting future-dated entries up front.

A schedule row per month is created when the batch is submitted. `post_due()` (run monthly, by hand or by the scheduler) turns every due,
still-valid row into a General Journal (type Prepayment: debit the expense, credit the prepaid account). Re-running it is always safe.
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import ROUND_DOWN, Decimal

from velora import ValidationError, get_doc, get_list, new_doc
from velora.exceptions import DoesNotExistError, PermissionDenied

from . import common as c

DT = "Amortisation Schedule"
FIELDS = ["name", "source_type", "source_ref", "voucher_type", "voucher_no", "line_no", "period_no", "period_count", "period_date", "amount",
          "expense_account", "prepaid_account", "status", "journal"]


def month_end(year: int, month: int) -> date:
    year, month = year + (month - 1) // 12, (month - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def split(amount: Decimal, periods: int) -> list[Decimal]:
    """Equal shares rounded DOWN to the cent; the last month takes the remainder, so the parts always add up exactly."""
    each = (amount / periods).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return [each] * (periods - 1) + [amount - each * (periods - 1)]


def schedule(*, voucher_type: str, voucher_no: str, source_type: str, source_ref: str, line_no: int, amount, start, periods: int,
             expense_account: str, prepaid_account: str) -> list[str]:
    amount, start = c.money(amount), c.to_date(start, "Amortise from")
    if periods < 2 or periods > 60:
        raise ValidationError("Spread over 2 to 60 months")
    names = []
    for i, part in enumerate(split(amount, periods)):
        d = month_end(start.year, start.month + i)
        names.append(new_doc(DT, source_type=source_type, source_ref=source_ref, voucher_type=voucher_type, voucher_no=voucher_no, line_no=line_no,
                             period_no=i + 1, period_count=periods, period_date=d, amount=part, expense_account=expense_account,
                             prepaid_account=prepaid_account, status="Scheduled").insert(ignore_permissions=True).name)
    return names


def _voucher_status(row) -> int | None:
    try:
        return get_doc(row["voucher_type"], row["voucher_no"], ignore_permissions=True).docstatus
    except DoesNotExistError:
        return None


def post_due(as_of=None) -> dict:
    """Post every scheduled month that has arrived. Returns {'posted': [...], 'waiting': [...], 'cancelled': [...], 'errors': [...]}."""
    if not c.has_role("Accounts Manager", "Accountant"):
        raise PermissionDenied("Only an Accountant or Accounts Manager can post amortisation")
    as_of = c.to_date(as_of, "As of") if as_of else date.today()
    out = {"posted": [], "waiting": [], "cancelled": [], "errors": []}
    rows = get_list(DT, filters=[["status", "=", "Scheduled"], ["period_date", "<=", as_of]], fields=FIELDS, order_by="period_date asc", limit=5000, ignore_permissions=True)
    rows.sort(key=lambda r: (r["period_date"], r["name"]))
    for r in rows:
        status = _voucher_status(r)
        sched = get_doc(DT, r["name"], ignore_permissions=True)
        if status == 0:
            out["waiting"].append(r["name"])                    # the payment is still a draft: nothing to recognise yet
            continue
        if status in (None, 2):                                  # the payment was deleted or cancelled
            sched.status = "Cancelled"
            sched.save(ignore_permissions=True)
            out["cancelled"].append(r["name"])
            continue
        try:
            gj = new_doc("General Journal", journal_type="Prepayment", posting_date=r["period_date"], source_type=DT, source_ref=r["name"],
                         reference=f"Amortisation {r['period_no']}/{r['period_count']} of {r['voucher_no']}", remarks=f"Amortisation of {r['voucher_no']}")
            gj.append("lines", {"account": r["expense_account"], "debit": r["amount"], "credit": 0})
            gj.append("lines", {"account": r["prepaid_account"], "debit": 0, "credit": r["amount"]})
            gj.insert(ignore_permissions=True).submit(ignore_permissions=True)
            sched.status, sched.journal = "Posted", gj.name
            sched.save(ignore_permissions=True)
            out["posted"].append(r["name"])
        except ValidationError as e:                             # e.g. the period is closed: report it, keep going
            out["errors"].append({"schedule": r["name"], "error": str(e)})
    return out


def cancel_for(source_type: str, source_ref: str) -> None:
    """Undo a batch's schedule: posted months are cancelled (their period must be open), waiting months are dropped."""
    for r in get_list(DT, filters=[["source_type", "=", source_type], ["source_ref", "=", source_ref], ["status", "!=", "Cancelled"]], fields=["name"],
                      order_by="period_no desc", limit=5000, ignore_permissions=True):
        s = get_doc(DT, r["name"], ignore_permissions=True)
        if s.status == "Posted" and s.journal:
            gj = get_doc("General Journal", s.journal, ignore_permissions=True)
            if gj.docstatus == 1:
                gj.cancel(ignore_permissions=True)
        s.status = "Cancelled"
        s.save(ignore_permissions=True)
