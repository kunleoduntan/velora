from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    least = int((filters or {}).get("min_days") or 1)
    today = date.today()
    names = I.names("Customer", "customer_name")
    rb = ReportBuilder("Collections Priority", [Column("rank", "#", "Int"), Column("invoice", "Invoice"), Column("customer", "Customer"), Column("due", "Due", "Date"), Column("late", "Days late", "Int"), Column("left", "Unpaid", "Currency"), Column("score", "Priority score", "Float"), Column("action", "Suggested action")])
    items = []
    for r in I.invoices("Sales Invoice"):
        late = (today - r["due_day"]).days if r["due_day"] else 0
        if r["outstanding"] > 0 and late >= least:
            items.append((float(r["outstanding"]) * late, late, r))
    for i, (score, late, r) in enumerate(sorted(items, key=lambda t: -t[0]), 1):
        rb.row({"rank": i, "invoice": r["name"], "customer": names.get(r["party"], r["party"]), "due": r["due_day"], "late": late, "left": r["outstanding"], "score": round(score, 1),
                "action": "Phone the finance contact today" if late > 60 else "Send a firm reminder" if late > 30 else "Send a friendly reminder"})
    return rb.build(summary=[{"label": "Overdue invoices", "value": len(rb.rows), "fieldtype": "Int"}, {"label": "Unpaid and late", "value": sum((r.values["left"] for r in rb.rows), Decimal(0)), "fieldtype": "Currency"}, {"label": "Over 60 days late", "value": sum(1 for r in rb.rows if r.values["late"] > 60), "fieldtype": "Int"}])
