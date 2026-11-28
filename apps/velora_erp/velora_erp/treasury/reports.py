"""Treasury report library: every Treasury report is a builder returning (columns, rows, totals)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from velora import get_doc, get_list, throw
from velora_erp.treasury import insight as ins, service as svc

D, ZERO = svc.D, Decimal(0)
C, N, DT = "Currency", "Float", "Date"


def f(v):
    return round(float(v or 0), 2)


def _dates(flt):
    a, b = flt.get("from_date"), flt.get("to_date")
    if a and b and str(a) > str(b):
        throw("From Date cannot be after To Date.")
    return svc.as_date(a), svc.as_date(b)


def portfolio(flt):
    cols = [("name", "Loan", "Data"), ("facility_name", "Facility", "Data"), ("lender", "Lender", "Data"), ("currency", "Currency", "Data"), ("drawdown_date", "Drawn", DT), ("maturity_date", "Matures", DT),
            ("rate", "Rate % now", N), ("outstanding", "Outstanding", C), ("accrued", "Accrued interest", C), ("overdue", "Overdue", C), ("next_due", "Next due", DT), ("next_amount", "Next amount", C),
            ("base", "Outstanding (base)", C)]
    rows = [{"name": p["name"], "facility_name": p["facility_name"], "lender": p["lender"], "currency": p["currency"], "drawdown_date": p["drawdown_date"], "maturity_date": p["maturity_date"],
             "rate": f(ins.effective_rate(p)), "outstanding": f(p["outstanding"]), "accrued": f(p["accrued"]), "overdue": f(p["overdue_amount"]), "next_due": p["next_due"], "next_amount": f(p["next_amount"]),
             "base": f(p["base_outstanding"])} for p in ins.portfolio() if (not flt.get("lender") or p["lender"] == flt["lender"])]
    return cols, rows, {"name": "Total", "base": round(sum(r["base"] for r in rows), 2), "overdue": round(sum(r["overdue"] for r in rows), 2), "accrued": round(sum(r["accrued"] for r in rows), 2)}


def ladder(flt):
    d = ins.dashboard()
    rows = [{"bucket": r["bucket"], "principal": f(r["principal"])} for r in d["ladder"]]
    tot = sum(r["principal"] for r in rows)
    for r in rows:
        r["percent"] = round(r["principal"] / tot * 100, 1) if tot else 0
    return [("bucket", "Maturity bucket", "Data"), ("principal", "Principal falling due", C), ("percent", "% of total", N)], rows, {"bucket": "Total", "principal": round(tot, 2)}


def service_schedule(flt):
    a, b = _dates(flt)
    names = {p["name"]: p for p in ins.portfolio()}
    rows = []
    for s in ins.schedule_lines():
        if flt.get("facility") and names.get(s["parent"], {}).get("facility") != flt["facility"]:
            continue
        if (a and s["due_date"] < a) or (b and s["due_date"] > b):
            continue
        p = names.get(s["parent"], {})
        rows.append({"due_date": s["due_date"], "loan": s["parent"], "facility_name": p.get("facility_name"), "lender": p.get("lender"), "currency": p.get("currency"), "principal": f(s["principal_open"]),
                     "interest": f(s["interest_open"]), "total": f(s["open"]), "base": f(s["open"] * D(p.get("fx_rate") or 1))})
    rows.sort(key=lambda r: (r["due_date"], r["loan"]))
    return ([("due_date", "Due", DT), ("loan", "Loan", "Data"), ("facility_name", "Facility", "Data"), ("lender", "Lender", "Data"), ("currency", "Currency", "Data"), ("principal", "Principal", C),
             ("interest", "Interest", C), ("total", "Total", C), ("base", "Total (base)", C)], rows,
            {"due_date": None, "loan": "Total", "principal": round(sum(r["principal"] for r in rows), 2), "interest": round(sum(r["interest"] for r in rows), 2), "total": round(sum(r["total"] for r in rows), 2), "base": round(sum(r["base"] for r in rows), 2)})


def amortisation(flt):
    if not flt.get("drawdown"):
        throw("Choose a drawdown.")
    dd = get_doc("Financing Drawdown", flt["drawdown"])
    rows = [{"number": l["number"], "due_date": l["due_date"], "opening": f(l["opening_principal"]), "principal": f(l["principal_due"]), "interest": f(l["interest_due"]), "total": f(l["total_due"]),
             "closing": f(l["closing_principal"]), "paid": f(D(l["principal_paid"]) + D(l["interest_paid"])), "status": l["status"]} for l in svc._lines(dd.name)]
    return ([("number", "No.", "Int"), ("due_date", "Due", DT), ("opening", "Opening principal", C), ("principal", "Principal", C), ("interest", "Interest", C), ("total", "Instalment", C),
             ("closing", "Closing principal", C), ("paid", "Paid", C), ("status", "Status", "Data")], rows,
            {"number": None, "principal": round(sum(r["principal"] for r in rows), 2), "interest": round(sum(r["interest"] for r in rows), 2), "total": round(sum(r["total"] for r in rows), 2), "paid": round(sum(r["paid"] for r in rows), 2)})


def interest_cost(flt):
    a, b = _dates(flt)
    acr = {r["name"]: r for r in get_list("Interest Accrual", filters=[["docstatus", "=", 1]], fields=["name", "accrual_date"], limit=5000, ignore_permissions=True)}
    rows = []
    for l in get_list("Interest Accrual Line", fields=["parent", "drawdown", "facility", "from_date", "to_date", "days", "principal_balance", "rate", "interest"], limit=20000, ignore_permissions=True):
        if l["parent"] not in acr:
            continue
        to = svc.as_date(l["to_date"])
        if (a and to < a) or (b and to > b) or (flt.get("facility") and l["facility"] != flt["facility"]):
            continue
        rows.append({"accrual": l["parent"], "drawdown": l["drawdown"], "facility": l["facility"], "from_date": svc.as_date(l["from_date"]), "to_date": to, "days": l["days"], "balance": f(l["principal_balance"]),
                     "rate": f(l["rate"]), "interest": f(l["interest"])})
    rows.sort(key=lambda r: (r["to_date"], r["drawdown"]))
    return ([("accrual", "Accrual", "Data"), ("drawdown", "Loan", "Data"), ("facility", "Facility", "Data"), ("from_date", "From", DT), ("to_date", "To", DT), ("days", "Days", "Int"), ("balance", "Principal", C),
             ("rate", "Rate %", N), ("interest", "Interest", C)], rows, {"accrual": "Total", "interest": round(sum(r["interest"] for r in rows), 2)})


def utilisation(flt):
    rows = [{"facility": x["name"], "facility_name": x["facility_name"], "lender": x["financial_institution"], "type": x["facility_type"], "currency": x["currency"], "limit": f(x["approved_limit"]),
             "drawn": f(x["total_drawn"]), "outstanding": f(x["outstanding_principal"]), "undrawn": f(x["undrawn_available"]), "percent": f(x["utilisation_percent"]), "expiry": x["expiry_date"],
             "days_left": (x["expiry_date"] - date.today()).days} for x in ins.facilities(True)]
    return ([("facility_name", "Facility", "Data"), ("lender", "Lender", "Data"), ("type", "Type", "Data"), ("currency", "Currency", "Data"), ("limit", "Approved limit", C), ("drawn", "Drawn to date", C),
             ("outstanding", "Outstanding", C), ("undrawn", "Available to draw", C), ("percent", "Used %", N), ("expiry", "Availability ends", DT), ("days_left", "Days left", "Int")], rows, None)


def liquidity(flt):
    lq = ins.liquidity(weeks=int(flt["weeks"]) if flt.get("weeks") else None)
    rows = [{"week": r["week"], "from": r["from"], "to": r["to"], "opening": f(r["opening"]), "receipts": f(r["receipts"]), "suppliers": f(r["suppliers"]), "debt": f(r["debt_service"]), "closing": f(r["closing"]),
             "flag": "Short" if r["short"] else ("Below buffer" if r["below_buffer"] else "")} for r in lq["rows"]]
    return ([("week", "Week", "Int"), ("from", "From", DT), ("to", "To", DT), ("opening", "Opening cash", C), ("receipts", "Customer receipts", C), ("suppliers", "Supplier payments", C),
             ("debt", "Debt service", C), ("closing", "Closing cash", C), ("flag", "Flag", "Data")], rows, None)


def fx(flt):
    rows = [{"currency": r["currency"], "receivables": f(r["receivables"]), "payables": f(r["payables"]), "debt": f(r["debt"]), "net": f(r["net"]), "rate": f(r["rate"]), "base_net": f(r["base_net"]),
             "gain": f(r["gain_if_stronger"]), "loss": f(r["loss_if_weaker"])} for r in ins.fx_exposure()]
    return ([("currency", "Currency", "Data"), ("receivables", "Receivables", C), ("payables", "Payables", C), ("debt", "Debt incl. accrued interest", C), ("net", "Net exposure", C), ("rate", "Rate to base", N),
             ("base_net", "Net (base)", C), ("gain", "If currency strengthens", C), ("loss", "If currency weakens", C)], rows, None)


def overdue(flt):
    today = date.today()
    ports = {p["name"]: p for p in ins.portfolio()}
    rows = []
    for s in ins.schedule_lines():
        if s["due_date"] >= today:
            continue
        p = ports.get(s["parent"], {})
        days = (today - s["due_date"]).days
        rows.append({"loan": s["parent"], "facility_name": p.get("facility_name"), "lender": p.get("lender"), "due_date": s["due_date"], "days": days,
                     "bucket": "1-30" if days <= 30 else "31-60" if days <= 60 else "61-90" if days <= 90 else "Over 90", "currency": p.get("currency"), "principal": f(s["principal_open"]),
                     "interest": f(s["interest_open"]), "total": f(s["open"])})
    rows.sort(key=lambda r: -r["days"])
    return ([("loan", "Loan", "Data"), ("facility_name", "Facility", "Data"), ("lender", "Lender", "Data"), ("due_date", "Was due", DT), ("days", "Days late", "Int"), ("bucket", "Age band", "Data"),
             ("currency", "Currency", "Data"), ("principal", "Principal", C), ("interest", "Interest", C), ("total", "Total", C)], rows, {"loan": "Total", "total": round(sum(r["total"] for r in rows), 2)})


def covenants(flt):
    rows = [{"facility_name": c["facility_name"], "covenant": c["covenant"], "measure": c["measure"], "test": f"{c['operator']} {c['threshold']}", "frequency": c["frequency"], "last_tested": c["last_tested"],
             "value": c["value"], "headroom": c["headroom"], "status": c["status"], "next_due": c["next_test_due"], "overdue": "Yes" if c["test_overdue"] else "No"} for c in ins.covenant_status()]
    return ([("facility_name", "Facility", "Data"), ("covenant", "Covenant", "Data"), ("measure", "Measure", "Data"), ("test", "Required", "Data"), ("frequency", "Tested", "Data"), ("last_tested", "Last tested", DT),
             ("value", "Result", N), ("headroom", "Headroom", N), ("status", "Status", "Data"), ("next_due", "Next test due", DT), ("overdue", "Test overdue", "Data")], rows, None)


def lenders(flt):
    by = defaultdict(lambda: {"loans": 0, "base": ZERO, "weighted": ZERO, "accrued": ZERO, "paid": ZERO})
    for p in ins.portfolio():
        b = by[p["lender"]]
        b["loans"] += 1; b["base"] += p["base_outstanding"]; b["weighted"] += p["base_outstanding"] * ins.effective_rate(p); b["accrued"] += p["base_accrued"]; b["paid"] += D(p["interest_paid"]) * p["fx_rate"]
    tot = sum((b["base"] for b in by.values()), ZERO)
    rows = [{"lender": k, "loans": b["loans"], "base": f(b["base"]), "share": f(b["base"] / tot * 100) if tot else 0, "rate": f(b["weighted"] / b["base"]) if b["base"] else 0, "accrued": f(b["accrued"]),
             "paid": f(b["paid"])} for k, b in sorted(by.items(), key=lambda x: -x[1]["base"])]
    return ([("lender", "Lender", "Data"), ("loans", "Loans", "Int"), ("base", "Outstanding (base)", C), ("share", "Share %", N), ("rate", "Weighted rate %", N), ("accrued", "Accrued interest (base)", C),
             ("paid", "Interest paid to date (base)", C)], rows, {"lender": "Total", "base": round(sum(r["base"] for r in rows), 2)})


def securities(flt):
    rows = []
    for x in ins.facilities(False):
        doc = get_doc("Financing Facility", x["name"], ignore_permissions=True)
        for s in doc.security or []:
            exp = svc.as_date(s.expiry_date)
            rows.append({"facility_name": x["facility_name"], "lender": x["financial_institution"], "security": s.security_type, "description": s.description, "value": f(s.value),
                         "registered": "Yes" if s.registered else "No", "reference": s.registration_reference, "expiry": exp, "outstanding": f(x["outstanding_principal"]),
                         "cover": f(D(s.value) / D(x["outstanding_principal"])) if D(x["outstanding_principal"]) else None})
    return ([("facility_name", "Facility", "Data"), ("lender", "Lender", "Data"), ("security", "Security", "Data"), ("description", "Description", "Data"), ("value", "Value", C), ("registered", "Registered", "Data"),
             ("reference", "Registration ref.", "Data"), ("expiry", "Expires", DT), ("outstanding", "Facility outstanding", C), ("cover", "Cover (x)", N)], rows, None)


BUILDERS = {"Debt Portfolio": portfolio, "Debt Maturity Ladder": ladder, "Debt Service Schedule": service_schedule, "Loan Amortisation Schedule": amortisation, "Interest Expense and Accrual": interest_cost,
            "Facility Utilisation and Headroom": utilisation, "Liquidity Forecast": liquidity, "FX Exposure and Sensitivity": fx, "Overdue Repayments": overdue, "Covenant Monitor": covenants,
            "Borrowing Cost by Lender": lenders, "Security Register": securities}


def run(name, filters=None):
    from velora.reporting import Column, ReportBuilder
    if name not in BUILDERS:
        throw(f"{name} is not a Treasury report.")
    cols, rows, total = BUILDERS[name](filters or {})
    rb = ReportBuilder(name, [Column(c, l, t) for c, l, t in cols])
    for r in rows:
        rb.row(r)
    if total and rows:
        rb.row(total)
    return rb
