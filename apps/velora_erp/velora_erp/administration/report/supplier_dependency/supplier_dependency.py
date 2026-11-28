from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    days = int((filters or {}).get("days") or 365)
    since = date.today() - timedelta(days=days)
    names = I.names("Supplier", "supplier_name")
    totals = {}
    for r in I.invoices("Purchase Invoice", since):
        totals[r["party"]] = totals.get(r["party"], Decimal(0)) + r["amount"]
    grand = sum(totals.values(), Decimal(0))
    rb = ReportBuilder("Supplier Dependency", [Column("rank", "#", "Int"), Column("party", "Supplier"), Column("amount", "Purchases", "Currency"), Column("share", "Share", "Percent"), Column("cum", "Running share", "Percent"), Column("band", "Class"), Column("advice", "What to do")])
    run, top80 = Decimal(0), 0
    for i, (party, amt) in enumerate(sorted(totals.items(), key=lambda kv: -kv[1]), 1):
        before = run
        run += amt
        share = I.pct(amt, grand)
        band = "A" if before / grand * 100 < 80 else "B" if before / grand * 100 < 95 else "C"
        top80 += 1 if band == "A" else 0
        rb.row({"rank": i, "party": names.get(party, party), "amount": amt, "share": share, "cum": I.pct(run, grand), "band": band, "advice": "Strategic: agree terms, keep a backup." if band == "A" else "Regular: compare prices." if band == "B" else "Occasional: consolidate."})
    first = rb.rows[0].values["share"] if rb.rows else 0
    notes = [f"One supplier is {first}% of purchases. Line up a second source."] if first > 30 else []
    return rb.build(summary=[{"label": "Purchases (last " + str(days) + " days)", "value": grand, "fieldtype": "Currency"}, {"label": "Suppliers", "value": len(totals), "fieldtype": "Int"}, {"label": "Make up 80%", "value": top80, "fieldtype": "Int"}, {"label": "Biggest share (%)", "value": first, "fieldtype": "Float"}], notes=notes)
