from datetime import date

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.engagement import service as svc


def execute(filters):
    filters = filters or {}
    ptype = filters.get("party_type") or "Customer"
    st = svc.settings()
    given = filters.get("quiet_days")
    threshold = int(given) if given not in (None, "") else int((st.get("winback_customer_days") if ptype == "Customer" else st.get("winback_supplier_days")) or 180)
    on = date.today()
    nudged = {}
    for r in get_list("Engagement Log", filters=[["kind", "=", "Win Back"], ["party_type", "=", ptype]], fields=["party", "moment_date"], limit=100000, ignore_permissions=True):
        d = svc._d(r["moment_date"])
        if d and (r["party"] not in nudged or d > nudged[r["party"]]):
            nudged[r["party"]] = d
    live = {p["name"]: p for p in svc._live_parties(ptype)}
    rb = ReportBuilder("Quiet Customers and Suppliers", [Column("party", "Party", "Data"), Column("name", "Name", "Data"), Column("last", "Last invoice", "Date"), Column("quiet", "Days quiet", "Int"),
                                                         Column("nudged", "Last nudge", "Date"), Column("email", "Email", "Data")])
    for party, last in sorted(svc.last_invoice_dates(ptype).items(), key=lambda kv: kv[1]):
        quiet = (on - last).days
        if party in live and quiet >= threshold:
            who = svc.contact(ptype, party) or {}
            rb.row({"party": party, "name": who.get("full_name") or party, "last": last, "quiet": quiet, "nudged": nudged.get(party), "email": who.get("email") or ""})
    return rb
