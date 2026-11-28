"""Shared, read-only helpers for the Administration and decision reports."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from velora import get_list


def D(x) -> Decimal:
    try:
        return Decimal(str(x or 0))
    except Exception:  # noqa: BLE001
        return Decimal(0)


def day(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10]) if x else None
    except ValueError:
        return None


def pct(part, whole) -> float:
    return round(float(D(part) / D(whole) * 100), 1) if D(whole) else 0.0


def invoices(doctype: str, since: date | None = None) -> list[dict]:
    """Submitted invoices with the amount in company currency and what is still unpaid (also in company currency)."""
    flt = [["docstatus", "=", 1]] + ([["invoice_date", ">=", since.isoformat()]] if since else [])
    out = []
    for r in get_list(doctype, filters=flt, fields=["name", "party", "invoice_date", "due_date", "grand_total", "base_grand_total", "amount_settled", "payment_status"], limit=500000, ignore_permissions=True):
        total, base, paid = D(r.get("grand_total")), D(r.get("base_grand_total")) or D(r.get("grand_total")), D(r.get("amount_settled"))
        left = max(Decimal(0), total - paid)
        r["amount"] = base
        r["outstanding"] = (base * left / total) if total else Decimal(0)
        r["invoice_day"], r["due_day"] = day(r.get("invoice_date")), day(r.get("due_date")) or day(r.get("invoice_date"))
        out.append(r)
    return out


def names(doctype: str, field: str) -> dict:
    return {r["name"]: r.get(field) or r["name"] for r in get_list(doctype, fields=["name", field], limit=500000, ignore_permissions=True)}


def months_back(n: int, today: date | None = None) -> list[date]:
    """First day of each of the last n months, oldest first."""
    t = (today or date.today()).replace(day=1)
    out = []
    for _ in range(n):
        out.append(t)
        t = (t - timedelta(days=1)).replace(day=1)
    return out[::-1]


def query(stmt) -> list[dict]:
    """Run a read-only statement against the company database (reports run outside a transaction)."""
    from velora import db
    with db.transaction() as c:
        return [dict(r) for r in c.execute(stmt).mappings()]


def role_rows():
    from velora.db.system import company_user_role
    from sqlalchemy import select
    return query(select(company_user_role))
