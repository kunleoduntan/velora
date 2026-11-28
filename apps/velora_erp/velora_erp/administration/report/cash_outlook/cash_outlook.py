from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

BUCKETS = [("Overdue", None, -1), ("Due in 0-30 days", 0, 30), ("Due in 31-60 days", 31, 60), ("Due in 61-90 days", 61, 90), ("Due later", 91, 10 ** 6)]


def _bucket(due, today):
    d = (due - today).days if due else 0
    for label, lo, hi in BUCKETS:
        if lo is None and d < 0 or lo is not None and lo <= d <= hi:
            return label
    return "Due later"


def execute(filters):
    today = date.today()
    money_in, money_out = {b[0]: Decimal(0) for b in BUCKETS}, {b[0]: Decimal(0) for b in BUCKETS}
    for target, doctype in ((money_in, "Sales Invoice"), (money_out, "Purchase Invoice")):
        for r in I.invoices(doctype):
            if r["outstanding"] > 0:
                target[_bucket(r["due_day"], today)] += r["outstanding"]
    rb = ReportBuilder("Cash Outlook", [Column("when", "When"), Column("inflow", "Customers owe you", "Currency"), Column("outflow", "You owe suppliers", "Currency"), Column("net", "Net", "Currency"), Column("run", "Cumulative net", "Currency"), Column("signal", "Signal")])
    run = Decimal(0)
    for label, _, _ in BUCKETS:
        net = money_in[label] - money_out[label]
        run += net
        rb.row({"when": label, "inflow": money_in[label], "outflow": money_out[label], "net": net, "run": run, "signal": "Healthy" if net >= 0 else "Cash squeeze"})
    ar, ap = sum(money_in.values(), Decimal(0)), sum(money_out.values(), Decimal(0))
    notes = ["Amounts are what remains unpaid on submitted invoices, by due date. Bank balances are not included."]
    return rb.build(summary=[{"label": "Owed to you", "value": ar, "fieldtype": "Currency"}, {"label": "You owe", "value": ap, "fieldtype": "Currency"}, {"label": "Net position", "value": ar - ap, "fieldtype": "Currency"}, {"label": "Overdue from customers", "value": money_in["Overdue"], "fieldtype": "Currency"}], notes=notes)
