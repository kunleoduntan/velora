from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def _segment(recency, orders, first_age):
    if recency <= 60 and orders >= 4: return "Champion", "Thank them and ask for referrals."
    if recency <= 120 and orders >= 2: return "Loyal", "Keep serving well; offer something new."
    if first_age <= 90 and orders == 1: return "New", "Welcome them and ask for feedback."
    if recency <= 365 and orders >= 2 and recency > 120: return "At risk", "Call before they leave."
    if recency > 365: return "Lost", "Send a win-back offer."
    return "Occasional", "Remind them what you offer."


def execute(filters):
    days = int((filters or {}).get("days") or 365)
    today = date.today()
    names = I.names("Customer", "customer_name")
    agg = {}
    for r in I.invoices("Sales Invoice", today - timedelta(days=max(days, 730))):
        a = agg.setdefault(r["party"], dict(last=None, first=None, n=0, spend=Decimal(0)))
        d = r["invoice_day"]
        if not d:
            continue
        a["last"] = d if a["last"] is None or d > a["last"] else a["last"]
        a["first"] = d if a["first"] is None or d < a["first"] else a["first"]
        if (today - d).days <= days:
            a["n"] += 1; a["spend"] += r["amount"]
    rb = ReportBuilder("Customer Segments", [Column("customer", "Customer"), Column("segment", "Segment"), Column("recency", "Days since last order", "Int"), Column("orders", "Orders", "Int"), Column("spend", "Spend", "Currency"), Column("action", "Suggested action")])
    counts = {}
    for party, a in sorted(agg.items(), key=lambda kv: -kv[1]["spend"]):
        seg, action = _segment((today - a["last"]).days, a["n"], (today - a["first"]).days)
        counts[seg] = counts.get(seg, 0) + 1
        rb.row({"customer": names.get(party, party), "segment": seg, "recency": (today - a["last"]).days, "orders": a["n"], "spend": a["spend"], "action": action})
    top = [{"label": k, "value": v, "fieldtype": "Int"} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]
    return rb.build(summary=top or [{"label": "Customers", "value": 0, "fieldtype": "Int"}])
