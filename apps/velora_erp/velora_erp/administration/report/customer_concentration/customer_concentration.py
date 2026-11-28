from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    days = int((filters or {}).get("days") or 365)
    since = date.today() - timedelta(days=days)
    names = I.names("Customer", "customer_name")
    totals = {}
    for r in I.invoices("Sales Invoice", since):
        totals[r["party"]] = totals.get(r["party"], Decimal(0)) + r["amount"]
    grand = sum(totals.values(), Decimal(0))
    rb = ReportBuilder("Customer Concentration", [Column("rank", "#", "Int"), Column("party", "Customer"), Column("amount", "Sales", "Currency"), Column("share", "Share", "Percent"), Column("cum", "Running share", "Percent"), Column("band", "Class"), Column("advice", "What to do")])
    run, top80 = Decimal(0), 0
    for i, (party, amt) in enumerate(sorted(totals.items(), key=lambda kv: -kv[1]), 1):
        before = run
        run += amt
        share = I.pct(amt, grand)
        band = "A" if before / grand * 100 < 80 else "B" if before / grand * 100 < 95 else "C"
        top80 += 1 if band == "A" else 0
        rb.row({"rank": i, "party": names.get(party, party), "amount": amt, "share": share, "cum": I.pct(run, grand), "band": band, "advice": "Protect: visit and reward." if band == "A" else "Grow: offer more." if band == "B" else "Nurture or let go."})
    first = rb.rows[0].values["share"] if rb.rows else 0
    notes = [f"One customer is {first}% of sales. Losing them would hurt badly: widen the base."] if first > 30 else []
    return rb.build(summary=[{"label": "Sales (last " + str(days) + " days)", "value": grand, "fieldtype": "Currency"}, {"label": "Customers", "value": len(totals), "fieldtype": "Int"}, {"label": "Make up 80%", "value": top80, "fieldtype": "Int"}, {"label": "Biggest share (%)", "value": first, "fieldtype": "Float"}], notes=notes)
