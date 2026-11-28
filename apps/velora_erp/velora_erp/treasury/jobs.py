"""Daily Treasury watch: keep facility status current, draft month-end interest accruals, and raise notifications.

Nothing is posted here. Accruals are created as drafts for the approval workflow; notifications fire the rules the user has set up for
the events `treasury_repayment_due`, `treasury_repayment_overdue`, `treasury_facility_expiring` and `treasury_covenant_test_due`.
"""
from __future__ import annotations

from datetime import date, timedelta

from velora import get_doc, new_doc
from velora_erp.treasury import insight, service as svc


def _fire(event, doc, key):
    try:
        from velora_notify.engine import trigger
        trigger(event, doc, key=key)
    except Exception:  # noqa: BLE001  (notification rules are optional)
        pass


def daily(today=None):
    today = today or date.today()
    out = {"accruals": [], "notified": 0}
    for f in svc.submitted("Financing Facility", [], ["name"]):
        svc.refresh_facility(f["name"])
    st = svc.settings()
    for p in insight.portfolio(today):
        dd = get_doc("Financing Drawdown", p["name"], ignore_permissions=True)
        if p["overdue_amount"] > 0:
            _fire("treasury_repayment_overdue", dd, f"overdue:{p['name']}:{today}"); out["notified"] += 1
        elif p["next_due"] and (p["next_due"] - today).days <= st["repayment_warning_days"]:
            _fire("treasury_repayment_due", dd, f"due:{p['name']}:{p['next_due']}"); out["notified"] += 1
    for f in insight.facilities(True):
        if 0 <= (f["expiry_date"] - today).days <= st["expiry_warning_days"]:
            _fire("treasury_facility_expiring", get_doc("Financing Facility", f["name"], ignore_permissions=True), f"expiry:{f['name']}:{today.year}-{today.month}"); out["notified"] += 1
    for c in insight.covenant_status(today):
        if c["test_overdue"]:
            _fire("treasury_covenant_test_due", get_doc("Financing Facility", c["facility"], ignore_permissions=True), f"cov:{c['facility']}:{c['covenant']}:{today.year}-{today.month}"); out["notified"] += 1
    if today.day <= 3:                                          # the first days of a month: a draft accrual through last month's end, per currency
        month_end = today.replace(day=1) - timedelta(days=1)
        for ccy in sorted({d["currency"] for d in svc.submitted("Financing Drawdown", [["status", "=", "Active"]], ["currency"])}):
            if svc.accrual_lines(ccy, month_end):
                if not svc.submitted("Interest Accrual", [["accrual_date", "=", month_end], ["currency", "=", ccy]], ["name"], limit=1) and \
                        not get_doc_list_draft(month_end, ccy):
                    doc = new_doc("Interest Accrual", accrual_date=month_end, currency=ccy, narration=f"Interest through {month_end} (created automatically)").insert(ignore_permissions=True)
                    out["accruals"].append(doc.name)
    return out


def get_doc_list_draft(month_end, ccy):
    from velora import get_list
    return get_list("Interest Accrual", filters=[["accrual_date", "=", month_end], ["currency", "=", ccy], ["docstatus", "=", 0]], fields=["name"], limit=1, ignore_permissions=True)
