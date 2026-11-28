"""Scheduled investment work: month-end income accrual and maturity warnings."""
from __future__ import annotations

from datetime import date, timedelta

from velora import get_doc, get_list, new_doc

from . import calculations as calc
from .posting import pre_accrual
from .settings import get_settings


def open_investments(fixed_only=False):
    out = []
    for row in get_list("Investment", filters={"docstatus": 1}, fields=["name", "status", "investment_class"], limit=100000, ignore_permissions=True):
        if row["status"] in ("Active", "Part Disposed") and (not fixed_only or calc.is_fixed_income(row["investment_class"])):
            out.append(row["name"])
    return out


def accrue(investment: str, as_of: date):
    """Recognise the income earned up to `as_of` on one investment. Returns the transaction name, or None when nothing is due."""
    inv = get_doc("Investment", investment, ignore_permissions=True)
    if pre_accrual(inv, as_of) <= 0:
        return None
    tx = new_doc("Investment Transaction", investment=investment, transaction_type="Income Accrual", transaction_date=as_of, narration="Income accrued to date").insert(ignore_permissions=True)
    tx.submit(ignore_permissions=True)
    return tx.name


def accrue_all(as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    made, failed = [], []
    for name in open_investments(fixed_only=True):
        try:
            tx = accrue(name, as_of)
            if tx:
                made.append(tx)
        except Exception as exc:  # noqa: BLE001 - one holding's problem must not stop the others
            failed.append({"investment": name, "error": str(exc)})
    return {"as_of": str(as_of), "posted": made, "failed": failed}


def accrue_month_end():
    """Daily task: on the last day of a month, recognise income to date when the company has switched automatic accrual on."""
    today = date.today()
    if not get_settings().get("auto_accrue") or today != calc.month_end(today):
        return {"skipped": True}
    return accrue_all(today)


def watch_maturities():
    """Daily task: tell the Notification Centre about investments maturing soon (rule event `investment_maturing`) when the notification app is installed."""
    try:
        from velora_notify import engine
    except Exception:  # noqa: BLE001 - notifications are optional
        return 0
    horizon = date.today() + timedelta(days=int(get_settings().get("maturity_alert_days") or 30))
    sent = 0
    for name in open_investments(fixed_only=True):
        inv = get_doc("Investment", name, ignore_permissions=True)
        if inv.maturity_date and date.today() <= inv.maturity_date <= horizon:
            sent += engine.trigger("investment_maturing", inv, key=str(inv.maturity_date))
    return sent
