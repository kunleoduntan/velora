from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    rb = ReportBuilder("Pending Approvals Ageing", [Column("doctype", "Document"), Column("name", "Number"), Column("party", "Party"), Column("amount", "Amount", "Currency"), Column("since", "Waiting since", "Date"), Column("days", "Days waiting", "Int"), Column("urgency", "Urgency")])
    today = date.today()
    for doctype in ("Sales Invoice", "Purchase Invoice"):
        for r in get_list(doctype, filters=[["approval_status", "=", "Pending"], ["docstatus", "!=", 2]], fields=["name", "party", "base_grand_total", "creation"], limit=100000, ignore_permissions=True):
            since = I.day(r.get("creation")) or today
            d = (today - since).days
            rb.row({"doctype": doctype, "name": r["name"], "party": r["party"], "amount": I.D(r["base_grand_total"]), "since": since, "days": d, "urgency": "Overdue: escalate" if d > 7 else "Chase today" if d > 3 else "Normal"})
    rb.rows.sort(key=lambda r: -r.values["days"])
    return rb.build(summary=[{"label": "Waiting", "value": len(rb.rows), "fieldtype": "Int"}, {"label": "Value waiting", "value": sum((r.values["amount"] for r in rb.rows), Decimal(0)), "fieldtype": "Currency"}, {"label": "Older than a week", "value": sum(1 for r in rb.rows if r.values["days"] > 7), "fieldtype": "Int"}])
