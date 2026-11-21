from datetime import date
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from .... import common as c

BUCKETS = [("not_due", "Not Due"), ("d30", "1-30 days"), ("d60", "31-60 days"), ("d90", "61-90 days"), ("d91", "Over 90 days")]


def bucket(days_overdue: int) -> str:
    return "not_due" if days_overdue <= 0 else "d30" if days_overdue <= 30 else "d60" if days_overdue <= 60 else "d90" if days_overdue <= 90 else "d91"


def execute(filters):
    as_of = c.to_date(filters.get("as_of") or date.today(), "Age as of")
    rows = get_list("Purchase Invoice", filters=[["docstatus", "=", 1], ["outstanding", ">", 0]], fields=["name", "supplier", "due_date", "outstanding"], limit=20000)
    per: dict[str, dict] = {}
    for r in rows:
        p = per.setdefault(r["supplier"], {k: Decimal(0) for k, _ in BUCKETS})
        p[bucket((as_of - r["due_date"]).days)] += Decimal(str(r["outstanding"]))
    rb = ReportBuilder("Aged Payables", [Column("party", "Supplier")] + [Column(k, label, "Currency") for k, label in BUCKETS] + [Column("total", "Total", "Currency")])
    for party in sorted(per):
        v = per[party]
        rb.row({"party": party, **v, "total": sum(v.values())})
    rb.total("Total outstanding")
    return rb
