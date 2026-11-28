from datetime import date, timedelta

from velora import throw
from velora.reporting import Column, ReportBuilder

from velora_erp.engagement import service as svc


def execute(filters):
    filters = filters or {}
    days = int(filters.get("days") or 14)
    if not 1 <= days <= 60:
        throw("Look ahead between 1 and 60 days.")
    start = svc._d(filters.get("from_date")) or date.today()
    st = svc.settings()
    rb = ReportBuilder("Upcoming Moments", [Column("when", "Date", "Date"), Column("kind", "Moment", "Data"), Column("party_type", "Type", "Data"), Column("party", "Party", "Data"),
                                            Column("name", "Name", "Data"), Column("occasion", "Occasion", "Data"), Column("source", "From", "Data")])
    kind = filters.get("kind")
    for i in range(days):
        day = start + timedelta(days=i)
        for m in svc.moments(day, st):
            if kind and m["kind"] != kind:
                continue
            who = svc.contact(m["party_type"], m["party"]) or {}
            rb.row({"when": day, "kind": m["kind"], "party_type": m["party_type"], "party": m["party"], "name": who.get("full_name") or "", "occasion": m.get("occasion") or "", "source": m.get("source") or ""})
            if len(rb.rows) >= 5000:
                throw("More than 5,000 moments. Look ahead fewer days or pick one kind.")
    return rb
