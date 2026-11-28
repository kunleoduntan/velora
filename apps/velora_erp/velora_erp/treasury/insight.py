"""Treasury insight: the portfolio, debt service, maturity, liquidity, currency exposure, covenant status and the adviser's findings.

Everything is read from the submitted documents and the ledger. Amounts in `base_*` are in the company's base currency.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from velora import db, get_list
from velora.db.tables import get_table
from velora_erp.treasury import service as svc

D, ZERO = svc.D, Decimal(0)
BUCKETS = [("Overdue", None, -1), ("Next 30 days", 0, 30), ("31-90 days", 31, 90), ("91-180 days", 91, 180), ("181-365 days", 181, 365), ("1-3 years", 366, 1095), ("3-5 years", 1096, 1825), ("Over 5 years", 1826, 10 ** 6)]
FREQ_DAYS = {"Monthly": 31, "Quarterly": 92, "Half-yearly": 183, "Annual": 366}


def f2(v):
    return round(float(v or 0), 2)


def rates_cache():
    cache = {}
    return lambda ccy, on=None: cache.setdefault(ccy, svc.rate_for(ccy, on) or Decimal(1))


def facilities(active_only=True):
    flt = [["docstatus", "=", 1]] + ([["status", "=", "Active"]] if active_only else [])
    rows = get_list("Financing Facility", filters=flt, fields=["name", "facility_name", "financial_institution", "facility_type", "currency", "approved_limit", "start_date", "expiry_date", "status", "interest_rate",
                                                              "interest_rate_type", "outstanding_principal", "total_drawn", "undrawn_available", "utilisation_percent", "accrued_interest_balance", "allows_redraw",
                                                              "secured", "repayment_structure", "wht_rule"], order_by="facility_name asc", limit=2000, ignore_permissions=True)
    for r in rows:
        r["expiry_date"], r["start_date"] = svc.as_date(r["expiry_date"]), svc.as_date(r["start_date"])
    return rows


def drawdowns(status="Active"):
    flt = [["docstatus", "=", 1]] + ([["status", "=", status]] if status else [])
    rows = get_list("Financing Drawdown", filters=flt, fields=["name", "facility", "drawdown_date", "amount", "currency", "exchange_rate", "interest_rate", "interest_rate_type", "maturity_date", "outstanding_principal",
                                                              "accrued_interest_balance", "interest_paid", "principal_repaid", "interest_accrued_to", "repayment_frequency", "tenor_months", "purpose"],
                    order_by="drawdown_date asc", limit=5000, ignore_permissions=True)
    for r in rows:
        r["drawdown_date"], r["maturity_date"] = svc.as_date(r["drawdown_date"]), svc.as_date(r["maturity_date"])
    return rows


def schedule_lines(names=None):
    t, p = get_table("Repayment Schedule Line"), get_table("Financing Drawdown")
    q = select(t).join(p, p.c.name == t.c.parent).where(p.c.docstatus == 1, p.c.status == "Active")
    if names:
        q = q.where(t.c.parent.in_(list(names)))
    with db.transaction() as c:
        out = [dict(r) for r in c.execute(q.order_by(t.c.parent, t.c.idx)).mappings()]
    for r in out:
        r["due_date"] = svc.as_date(r["due_date"])
        r["principal_open"] = max(ZERO, D(r["principal_due"]) - D(r["principal_paid"]))
        r["interest_open"] = max(ZERO, D(r["interest_due"]) - D(r["interest_paid"]))
        r["open"] = r["principal_open"] + r["interest_open"]
    return [r for r in out if r["open"] > 0]


def portfolio(today=None):
    """One row per active loan, with what is due next and what is overdue."""
    today = today or date.today()
    facs = {f["name"]: f for f in facilities(False)}
    lenders = {}
    rate = rates_cache()
    lines = defaultdict(list)
    for l in schedule_lines():
        lines[l["parent"]].append(l)
    rows = []
    for d in drawdowns():
        f = facs.get(d["facility"], {})
        ls = lines.get(d["name"], [])
        overdue = [l for l in ls if l["due_date"] < today]
        nxt = next((l for l in ls if l["due_date"] >= today), None)
        x = rate(d["currency"], today)
        rows.append({**d, "facility_name": f.get("facility_name"), "lender": f.get("financial_institution"), "facility_type": f.get("facility_type"), "rate_now": D(d["interest_rate"]),
                     "fx_rate": x, "outstanding": D(d["outstanding_principal"]), "base_outstanding": D(d["outstanding_principal"]) * x, "accrued": D(d["accrued_interest_balance"]),
                     "base_accrued": D(d["accrued_interest_balance"]) * x, "overdue_amount": sum((l["open"] for l in overdue), ZERO), "overdue_days": (today - overdue[0]["due_date"]).days if overdue else 0,
                     "next_due": nxt["due_date"] if nxt else None, "next_amount": nxt["open"] if nxt else ZERO, "days_to_maturity": (d["maturity_date"] - today).days if d["maturity_date"] else None,
                     "security": f.get("secured")})
    return rows


def effective_rate(row, timeline_cache={}):
    """The rate in force today for a loan (floating loans follow amendments)."""
    from velora_erp.treasury.engine import rate_function
    return rate_function(svc.rate_timeline(row))(date.today())


def covenant_status(today=None):
    """Latest test of every covenant on every active facility, and whether the next test is overdue."""
    today = today or date.today()
    tests = defaultdict(list)
    for t in get_list("Covenant Test", fields=["facility", "covenant_name", "tested_on", "actual_value", "status", "headroom", "threshold", "operator"], order_by="tested_on desc", limit=5000, ignore_permissions=True):
        tests[(t["facility"], t["covenant_name"].lower())].append(t)
    out = []
    for fac in get_list("Financing Facility", filters=[["docstatus", "=", 1], ["status", "=", "Active"]], fields=["name", "facility_name"], limit=2000, ignore_permissions=True):
        from velora import get_doc
        doc = get_doc("Financing Facility", fac["name"], ignore_permissions=True)
        for c in doc.covenants or []:
            hist = tests.get((fac["name"], c.covenant_name.lower()), [])
            last = hist[0] if hist else None
            due_by = svc.as_date(last["tested_on"]) + timedelta(days=FREQ_DAYS.get(c.test_frequency, 92)) if last else svc.as_date(doc.start_date)
            out.append({"facility": fac["name"], "facility_name": fac["facility_name"], "covenant": c.covenant_name, "measure": c.metric, "operator": c.operator, "threshold": c.threshold, "frequency": c.test_frequency,
                        "last_tested": svc.as_date(last["tested_on"]) if last else None, "value": last["actual_value"] if last else None, "status": last["status"] if last else "Never tested",
                        "headroom": last["headroom"] if last else None, "next_test_due": due_by, "test_overdue": due_by < today})
    return out


def bank_balances():
    from velora_erp.finance.engine import get_account_balance
    rows = get_list("Account", filters=[["account_type", "in", ["BANK", "CASH"]], ["is_group", "=", 0], ["disabled", "=", 0]], fields=["name", "account_name"], limit=500, ignore_permissions=True)
    return [{"account": r["name"], "name": r["account_name"], "balance": D(get_account_balance(r["name"]))} for r in rows]


def _open_invoices(doctype, today):
    out = []
    for r in get_list(doctype, filters=[["docstatus", "=", 1]], fields=["name", "party", "due_date", "grand_total", "amount_settled", "currency", "exchange_rate"], limit=20000, ignore_permissions=True):
        open_ = D(r["grand_total"]) - D(r["amount_settled"])
        if open_ > 0:
            out.append({**r, "due_date": svc.as_date(r["due_date"]) or today, "open_base": open_ * D(r["exchange_rate"] or 1)})
    return out


def liquidity(today=None, weeks=None):
    """Week-by-week cash: receivables falling due, supplier payments, debt service, against today's bank balances."""
    today = today or date.today()
    st = svc.settings()
    weeks = int(weeks or st["forecast_weeks"])
    buffer = D(st["minimum_cash_buffer"])
    opening = sum((b["balance"] for b in bank_balances()), ZERO)
    ar, ap = _open_invoices("Sales Invoice", today), _open_invoices("Purchase Invoice", today)
    ds = schedule_lines()
    rate = rates_cache()
    drawn = {d["name"]: rate(d["currency"], today) for d in drawdowns()}
    rows, cash = [], opening
    for w in range(weeks):
        a, b = today + timedelta(days=7 * w), today + timedelta(days=7 * (w + 1))
        inn = lambda x: (x["due_date"] < b if w == 0 else a <= x["due_date"] < b)
        rec = sum((x["open_base"] for x in ar if a <= x["due_date"] < b), ZERO)
        pay = sum((x["open_base"] for x in ap if (x["due_date"] < b if w == 0 else a <= x["due_date"] < b)), ZERO)       # what is already overdue to suppliers must be paid first
        debt = sum((x["open"] * drawn.get(x["parent"], Decimal(1)) for x in ds if (x["due_date"] < b if w == 0 else a <= x["due_date"] < b)), ZERO)
        close = cash + rec - pay - debt
        rows.append({"week": w + 1, "from": a, "to": b - timedelta(days=1), "opening": cash, "receipts": rec, "suppliers": pay, "debt_service": debt, "closing": close, "below_buffer": close < buffer, "short": close < 0})
        cash = close
    return {"opening": opening, "rows": rows, "overdue_receivables": sum((x["open_base"] for x in ar if x["due_date"] < today), ZERO), "buffer": buffer,
            "assumption": "Receivables are assumed collected on their due date; receivables already overdue are not counted until they are paid. Payables already overdue are assumed paid in week 1. Tax remittances and payroll are not forecast here."}


def fx_exposure(today=None):
    today = today or date.today()
    base = svc.base_currency()
    shock = D(svc.settings()["fx_shock_percent"]) / 100
    rate = rates_cache()
    book = defaultdict(lambda: {"debt": ZERO, "receivables": ZERO, "payables": ZERO})
    for d in drawdowns():
        if d["currency"] != base:
            book[d["currency"]]["debt"] += D(d["outstanding_principal"]) + D(d["accrued_interest_balance"])
    for doctype, key in (("Sales Invoice", "receivables"), ("Purchase Invoice", "payables")):
        for r in get_list(doctype, filters=[["docstatus", "=", 1], ["currency", "!=", base]], fields=["currency", "grand_total", "amount_settled"], limit=20000, ignore_permissions=True):
            book[r["currency"]][key] += D(r["grand_total"]) - D(r["amount_settled"])
    out = []
    for ccy, b in sorted(book.items()):
        net = b["receivables"] - b["payables"] - b["debt"]
        x = rate(ccy, today)
        out.append({"currency": ccy, **b, "net": net, "rate": x, "base_net": net * x, "gain_if_stronger": net * x * shock, "loss_if_weaker": -net * x * shock, "base_debt": b["debt"] * x})
    return out


def dashboard(today=None):
    today = today or date.today()
    st = svc.settings()
    pf = portfolio(today)
    facs = facilities(True)
    rate = rates_cache()
    total = sum((p["base_outstanding"] for p in pf), ZERO)
    wavg = (sum((p["base_outstanding"] * effective_rate(p) for p in pf), ZERO) / total) if total else ZERO
    floating = sum((p["base_outstanding"] for p in pf if p["interest_rate_type"] == "Floating"), ZERO)
    sched = schedule_lines()
    x = {d["name"]: rate(d["currency"], today) for d in drawdowns()}
    due = lambda n: sum((s["open"] * x.get(s["parent"], Decimal(1)) for s in sched if s["due_date"] <= today + timedelta(days=n)), ZERO)
    undrawn = sum((D(f["undrawn_available"]) * rate(f["currency"], today) for f in facs if f["expiry_date"] >= today), ZERO)
    lenders = defaultdict(lambda: ZERO)
    for p in pf:
        lenders[p["lender"]] += p["base_outstanding"]
    cov = covenant_status(today)
    counts = defaultdict(int)
    for c in cov:
        counts[c["status"]] += 1
    cash = sum((b["balance"] for b in bank_balances()), ZERO)
    ladder = []
    for label, lo, hi in BUCKETS:
        amt = ZERO
        for s in sched:
            n = (s["due_date"] - today).days
            if (lo is None and n <= hi) or (lo is not None and lo <= n <= hi):
                amt += D(s["principal_open"]) * x.get(s["parent"], Decimal(1))
        ladder.append({"bucket": label, "principal": amt})
    fx = fx_exposure(today)
    finds = adviser(today, pf=pf, facs=facs, cov=cov, cash=cash, total=total, lenders=lenders)
    return {"total_debt": total, "weighted_rate": wavg, "floating_share": (floating / total * 100) if total else ZERO, "undrawn": undrawn, "facilities": len(facs), "loans": len(pf),
            "debt_service_30": due(30), "debt_service_90": due(90), "overdue_amount": sum((p["overdue_amount"] * p["fx_rate"] for p in pf), ZERO), "overdue_loans": sum(1 for p in pf if p["overdue_amount"] > 0),
            "accrued_unpaid": sum((p["base_accrued"] for p in pf), ZERO), "cash": cash, "net_debt": total - cash, "rate_shock_cost": floating * D(st["rate_shock_points"]) / 100,
            "rate_shock_points": st["rate_shock_points"], "covenants": dict(counts), "tests_overdue": sum(1 for c in cov if c["test_overdue"]),
            "foreign_debt": sum((e["base_debt"] for e in fx), ZERO), "lenders": sorted(({"lender": k, "amount": v, "percent": (v / total * 100) if total else ZERO} for k, v in lenders.items()), key=lambda r: -r["amount"]),
            "ladder": ladder, "facility_usage": [{"name": f["facility_name"], "limit": f["approved_limit"], "outstanding": f["outstanding_principal"], "percent": f["utilisation_percent"], "currency": f["currency"], "expires": f["expiry_date"]} for f in facs],
            "findings": finds, "finding_counts": {k: sum(1 for f in finds if f["severity"] == k) for k in ("critical", "warning", "info")}, "base_currency": svc.base_currency()}


def adviser(today=None, **cached):
    """What a treasury consultant would tell the finance director this morning."""
    today = today or date.today()
    st = svc.settings()
    pf = cached.get("pf") or portfolio(today)
    facs = cached.get("facs") or facilities(True)
    cov = cached.get("cov") if cached.get("cov") is not None else covenant_status(today)
    cash = cached.get("cash") if cached.get("cash") is not None else sum((b["balance"] for b in bank_balances()), ZERO)
    total = cached.get("total") if cached.get("total") is not None else sum((p["base_outstanding"] for p in pf), ZERO)
    lenders = cached.get("lenders")
    if lenders is None:
        lenders = defaultdict(lambda: ZERO)
        for p in pf:
            lenders[p["lender"]] += p["base_outstanding"]
    out = []
    add = lambda sev, area, title, detail, route=None: out.append({"severity": sev, "area": area, "title": title, "detail": detail, "route": route})
    for p in pf:
        if p["overdue_amount"] > 0:
            add("critical", "Repayments", f"{p['facility_name']}: {p['overdue_amount']:,.2f} {p['currency']} overdue for {p['overdue_days']} days", "Pay it or agree a waiver with the lender; late payment can trigger default and cross-default clauses.", "Financing Repayment")
    soon = st["repayment_warning_days"]
    for p in pf:
        if p["next_due"] and (p["next_due"] - today).days <= soon and p["overdue_amount"] == 0:
            add("warning", "Repayments", f"{p['facility_name']}: {p['next_amount']:,.2f} {p['currency']} due {p['next_due']}", f"Due in {(p['next_due'] - today).days} days. Make sure the funds are in the paying account.", "Financing Repayment")
    for f in facs:
        if float(f["utilisation_percent"] or 0) >= float(st["utilisation_alert_percent"]):
            add("warning", "Headroom", f"{f['facility_name']} is {float(f['utilisation_percent']):.0f}% used", f"Only {D(f['undrawn_available']):,.2f} {f['currency']} left to draw. Ask for an increase before you need it.", "Financing Facility")
        days = (f["expiry_date"] - today).days
        if 0 <= days <= int(st["expiry_warning_days"]):
            add("warning", "Headroom", f"{f['facility_name']} availability ends in {days} days", "Start the renewal now: lenders need weeks to approve.", "Financing Facility")
        if days < 0 and D(f["outstanding_principal"]) > 0:
            add("info", "Headroom", f"{f['facility_name']} can no longer be drawn but {D(f['outstanding_principal']):,.2f} is still outstanding", "The facility is past its availability date; repayments continue on the schedule.", "Financing Facility")
    for c in cov:
        if c["status"] == "Breach":
            add("critical", "Covenants", f"{c['facility_name']}: {c['covenant']} breached", f"Measured {c['value']} against a limit of {c['operator']} {c['threshold']}. Seek a waiver before the lender acts.", "Covenant Test")
        elif c["status"] == "Warning":
            add("warning", "Covenants", f"{c['facility_name']}: {c['covenant']} is close to its limit", f"Measured {c['value']} against {c['operator']} {c['threshold']}; headroom {c['headroom']}.", "Covenant Test")
        if c["test_overdue"]:
            add("warning", "Covenants", f"{c['facility_name']}: {c['covenant']} has not been tested since {c['last_tested'] or 'the facility started'}", f"It is tested {c['frequency'].lower()}.", "Covenant Test")
    acc = [p for p in pf if (p["interest_accrued_to"] and (today - svc.as_date(p["interest_accrued_to"])).days > 35)]
    if acc:
        add("warning", "Accounting", f"Interest has not been accrued for {len(acc)} loan(s) for over a month", "Run Interest Accrual so the period's cost is in the accounts.", "Interest Accrual")
    if total > 0:
        for lender, amt in lenders.items():
            pct = amt / total * 100
            if pct >= D(st["lender_concentration_percent"]) and len(lenders) > 1:
                add("info", "Risk", f"{pct:.0f}% of your debt is with {lender}", "A concentration with one lender raises refinancing risk.", "Financial Institution")
        floating = sum((p["base_outstanding"] for p in pf if p["interest_rate_type"] == "Floating"), ZERO)
        if floating / total > Decimal("0.5"):
            cost = floating * D(st["rate_shock_points"]) / 100
            add("info", "Risk", f"{float(floating / total * 100):.0f}% of your debt has a floating rate", f"A {st['rate_shock_points']}-point rise in rates would cost about {cost:,.2f} a year.", "Treasury Centre")
    for e in fx_exposure(today):
        if e["net"] < 0 and abs(e["base_net"]) > 0:
            add("warning", "Currency", f"Unhedged {e['currency']} exposure of {abs(e['net']):,.2f}", f"A {st['fx_shock_percent']}% weaker {svc.base_currency()} would cost about {abs(e['loss_if_weaker']):,.2f}. Consider matching receipts or hedging.", "FX Exposure and Sensitivity")
    ds30 = sum((s["open"] for s in schedule_lines() if s["due_date"] <= today + timedelta(days=30)), ZERO)
    if ds30 > 0 and cash < ds30:
        add("critical", "Liquidity", f"Cash of {cash:,.2f} does not cover {ds30:,.2f} of debt service due in 30 days", "Arrange funding or collect receivables now. See the Liquidity Forecast.", "Liquidity Forecast")
    for f in facs:
        if f.get("wht_rule") is None:
            lender = get_list("Financial Institution", filters=[["name", "=", f["financial_institution"]]], fields=["wht_applicable"], limit=1, ignore_permissions=True)
            if lender and lender[0]["wht_applicable"] and not st["default_interest_wht_rule"]:
                add("warning", "Tax", f"{f['facility_name']}: the lender is subject to withholding tax but no rule is set", "Set a withholding tax rule on the facility so each interest payment withholds tax.", "Financing Facility")
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(out, key=lambda x: order[x["severity"]])
