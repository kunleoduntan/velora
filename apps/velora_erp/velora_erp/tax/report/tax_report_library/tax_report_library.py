from datetime import date
from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.tax import library


def execute(filters):
    check_access()
    f = filters or {}
    if not f.get("report"):
        throw("Choose a report.")
    today = date.today()
    start = f.get("from_date") or date(today.year, 1, 1)
    end = f.get("to_date") or today
    cols, rows = library.run(f["report"], start, end, f.get("tax_type"), f.get("jurisdiction"), f.get("party"))
    rb = ReportBuilder(f["report"], [Column(k, label, t) for k, label, t in cols])
    for r in rows:
        rb.row(r)
    return rb
