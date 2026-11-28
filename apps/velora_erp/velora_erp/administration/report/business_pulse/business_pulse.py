from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I
from velora.meta.registry import registry


def _chg(now, before):
    return round(float((I.D(now) - I.D(before)) / I.D(before) * 100), 1) if I.D(before) else None


def _signal(c, good_up=True):
    if c is None or abs(c) < 3:
        return "Steady"
    return "Good" if (c > 0) == good_up else "Watch"


def execute(filters):
    today = date.today()
    this_m = today.replace(day=1)
    last_m = (this_m - timedelta(days=1)).replace(day=1)
    sales, buys = I.invoices("Sales Invoice", last_m), I.invoices("Purchase Invoice", last_m)

    def span(rows, a, b):
        return sum((r["amount"] for r in rows if r["invoice_day"] and a <= r["invoice_day"] < b), Decimal(0))

    ar_all, ap_all = I.invoices("Sales Invoice"), I.invoices("Purchase Invoice")
    ar = sum((r["outstanding"] for r in ar_all), Decimal(0))
    ap = sum((r["outstanding"] for r in ap_all), Decimal(0))
    late = sum((r["outstanding"] for r in ar_all if r["due_day"] and r["due_day"] < today), Decimal(0))
    pending = sum(len(get_list(d, filters=[["approval_status", "=", "Pending"], ["docstatus", "!=", 2]], fields=["name"], limit=100000, ignore_permissions=True)) for d in ("Sales Invoice", "Purchase Invoice"))
    held = len(get_list("Engagement Log", filters=[["status", "=", "Held"]], fields=["name"], limit=100000, ignore_permissions=True)) if registry.exists("Engagement Log") else 0
    staff = len(get_list("Employee", filters=[["employment_status", "=", "Active"]], fields=["name"], limit=100000, ignore_permissions=True)) if registry.exists("Employee") else 0
    rb = ReportBuilder("Business Pulse", [Column("metric", "Measure"), Column("now", "Now", "Float"), Column("before", "Before", "Float"), Column("change", "Change", "Percent"), Column("signal", "Signal"), Column("next", "Next step")])
    nxt = span(sales, last_m, this_m)
    c = _chg(span(sales, this_m, today + timedelta(days=1)), nxt)
    rb.row({"metric": "Sales this month so far vs all of last month", "now": span(sales, this_m, today + timedelta(days=1)), "before": nxt, "change": c, "signal": _signal(c), "next": "Early in the month this looks low; compare again later."})
    pb = span(buys, last_m, this_m)
    c = _chg(span(buys, this_m, today + timedelta(days=1)), pb)
    rb.row({"metric": "Purchases this month so far vs all of last month", "now": span(buys, this_m, today + timedelta(days=1)), "before": pb, "change": c, "signal": _signal(c, good_up=False), "next": "Check big purchases are planned."})
    rb.row({"metric": "Customers owe you", "now": ar, "before": None, "change": None, "signal": "Watch" if ar and late / ar > Decimal("0.3") else "Good", "next": "Chase the overdue invoices (see Collections Priority)."})
    rb.row({"metric": "...of which overdue", "now": late, "before": None, "change": None, "signal": "Watch" if late else "Good", "next": "Phone the biggest first."})
    rb.row({"metric": "You owe suppliers", "now": ap, "before": None, "change": None, "signal": "Steady", "next": "Plan payments against Cash Outlook."})
    rb.row({"metric": "Invoices waiting for approval", "now": pending, "before": None, "change": None, "signal": "Watch" if pending > 10 else "Good", "next": "See Pending Approvals Ageing."})
    rb.row({"metric": "Greetings held, not yet sent", "now": held, "before": None, "change": None, "signal": "Watch" if held else "Good", "next": "Release them in Engagement Log or switch on automatic sending."})
    rb.row({"metric": "Active employees", "now": staff, "before": None, "change": None, "signal": "Steady", "next": ""})
    good = sum(1 for r in rb.rows if r.values["signal"] == "Good"); watch = sum(1 for r in rb.rows if r.values["signal"] == "Watch")
    return rb.build(summary=[{"label": "Looking good", "value": good, "fieldtype": "Int"}, {"label": "Needs a look", "value": watch, "fieldtype": "Int"}])
