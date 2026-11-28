from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    n = max(3, min(36, int((filters or {}).get("months") or 12)))
    months = I.months_back(n)
    sales, buys = {m: Decimal(0) for m in months}, {m: Decimal(0) for m in months}
    for target, doctype in ((sales, "Sales Invoice"), (buys, "Purchase Invoice")):
        for r in I.invoices(doctype, months[0]):
            d = r["invoice_day"]
            if d:
                target[d.replace(day=1)] = target.get(d.replace(day=1), Decimal(0)) + r["amount"]
    rb = ReportBuilder("Sales and Purchases Trend", [Column("month", "Month"), Column("sales", "Sales", "Currency"), Column("growth", "Sales growth", "Percent"), Column("purchases", "Purchases", "Currency"), Column("spread", "Sales less purchases", "Currency"), Column("signal", "Signal")])
    prev = None
    for m in months:
        s, p = sales[m], buys[m]
        g = round(float((s - prev) / prev * 100), 1) if prev else None
        rb.row({"month": m.strftime("%b %Y"), "sales": s, "growth": g, "purchases": p, "spread": s - p, "signal": "Growing" if g is not None and g > 5 else "Falling" if g is not None and g < -5 else "Steady" if g is not None else ""})
        prev = s if s else prev
    tot_s, tot_p = sum(sales.values(), Decimal(0)), sum(buys.values(), Decimal(0))
    best = max(months, key=lambda m: sales[m])
    return rb.build(summary=[{"label": "Sales", "value": tot_s, "fieldtype": "Currency"}, {"label": "Purchases", "value": tot_p, "fieldtype": "Currency"}, {"label": "Best month: " + best.strftime("%b %Y"), "value": sales[best], "fieldtype": "Currency"}])
