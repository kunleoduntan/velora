from datetime import date

from velora import get_list
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.tax.service import OPEN_STATES


def execute(filters):
    check_access()
    f = filters or {}
    flt = []
    if f.get("from_date"): flt.append(["due_date", ">=", f["from_date"]])
    if f.get("to_date"): flt.append(["due_date", "<=", f["to_date"]])
    if f.get("open_only"): flt.append(["status", "in", list(OPEN_STATES)])
    rows = get_list("Tax Obligation", filters=flt, fields=["name", "tax_type", "jurisdiction", "period_end", "due_date", "status", "owner_user", "tax_return", "filing_reference"], order_by="due_date", limit=5000)
    today = date.today()
    rb = ReportBuilder("Tax Obligation Calendar", [Column("name", "Obligation"), Column("tax_type", "Tax"), Column("jurisdiction", "Jurisdiction"), Column("period_end", "Period End", "Date"),
        Column("due_date", "Due", "Date"), Column("status", "Status"), Column("days", "Days Left / (Overdue)", "Int"), Column("owner_user", "Owner"), Column("tax_return", "Return")])
    for r in rows:
        days = (date.fromisoformat(str(r["due_date"])[:10]) - today).days
        rb.row({**r, "days": days if r["status"] in OPEN_STATES else None})
    return rb
