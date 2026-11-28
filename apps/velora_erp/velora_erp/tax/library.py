"""Tax Report Library: executable reports built from the tax ledger and the tax documents.

Each report is a function of a Context (period, filters, cached facts) returning (columns, rows). The registry REG maps the
catalogue's report name to its builder, so the catalogue shows exactly what can be run. Reports that need data this system does not
hold (transfer pricing files, audit cases, integrations) are not here, and the catalogue says so.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from velora import db, get_doc, get_list
from velora.db.tables import get_table
from velora_erp.tax.facts import as_date, facts as load_facts, rule_index
from velora_erp.tax.service import OPEN_STATES, _d, load_rules, settings

ZERO = Decimal("0")
REG: dict = {}
DOMAIN: dict = {}
M, I, P, T, DT = "Currency", "Int", "Float", "Data", "Date"


def report(name, domain=None):
    def deco(fn):
        REG[name] = fn; DOMAIN[name] = domain
        return fn
    return deco


class Ctx:
    def __init__(self, start, end, tax_type=None, jurisdiction=None, party=None):
        self.start, self.end, self.tax_type, self.jurisdiction, self.party = as_date(start), as_date(end), tax_type or None, jurisdiction or None, party or None
        self.today = date.today()
        self._f = {}

    def facts(self, start=None, end=None):
        key = (start or self.start, end or self.end)
        if key not in self._f:
            rows = load_facts(*key)
            self._f[key] = [r for r in rows if (not self.tax_type or r["tax_type"] == self.tax_type) and (not self.jurisdiction or r["jurisdiction"] == self.jurisdiction)
                            and (not self.party or r["party"] == self.party)]
        return self._f[key]


def f2(v): return round(float(v or 0), 2)
def month(d): return f"{d.year}-{d.month:02d}"
def quarter(d): return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
def year(d): return str(d.year)


def pivot(rows, dims, extra=None, sort="tax"):
    """Group fact rows by dims [(field, label)] with count, taxable amount, output tax, input tax and net (output - input)."""
    acc = defaultdict(lambda: {"n": 0, "net": ZERO, "out": ZERO, "inp": ZERO})
    for r in rows:
        a = acc[tuple((d(r["date"]) if d in (month, quarter, year) else r[d]) for d, _ in dims)]
        a["n"] += 1; a["net"] += r["net"]
        if r["section"] == "Output": a["out"] += r["tax"]
        else: a["inp"] += r["tax"]
    cols = [(f"d{i}", lab, T) for i, (_, lab) in enumerate(dims)] + [("n", "Entries", I), ("net", "Taxable Amount", M), ("out", "Tax Payable-type (output / withheld by us)", M), ("inp", "Tax Credit-type (input / suffered)", M), ("net_tax", "Net (payable less credit)", M)]
    out = []
    for key, a in sorted(acc.items(), key=lambda kv: -abs(float(kv[1]["out"] + kv[1]["inp"])) if sort == "tax" else kv[0]):
        row = {f"d{i}": (k if k not in (None, "") else "(none)") for i, k in enumerate(key)}
        row.update(n=a["n"], net=f2(a["net"]), out=f2(a["out"]), inp=f2(a["inp"]), net_tax=f2(a["out"] - a["inp"]))
        out.append(row)
    return cols, out


def pv(name, domain, dims, pred=None):
    def fn(c):
        rows = [r for r in c.facts() if (pred(r) if pred else True)]
        return pivot(rows, dims, sort="key" if dims and dims[0][0] in (month, quarter, year) else "tax")
    return report(name, domain)(fn)


VAT = lambda r: r["tax_type"] == "VAT"
WHT = lambda r: r["tax_type"] == "WHT"
for _n, _dims, _p in [
    ("VAT by Tax Rate", [("rate", "Rate %")], VAT), ("VAT by Tax Category", [("category", "Category")], VAT), ("VAT by Customer", [("party", "Customer")], lambda r: VAT(r) and r["section"] == "Output"),
    ("VAT by Supplier", [("party", "Supplier")], lambda r: VAT(r) and r["section"] == "Input"), ("VAT by Item", [("item", "Item")], VAT), ("VAT by Account", [("account", "Account"), ("account_name", "Name")], VAT),
    ("VAT by Jurisdiction", [("jurisdiction", "Jurisdiction")], VAT), ("WHT by Category", [("category", "Category")], WHT), ("WHT by Rate", [("rate", "Rate %")], WHT),
    ("Tax by Jurisdiction", [("jurisdiction", "Jurisdiction")], None), ("Tax by Tax Type", [("tax_type", "Tax type")], None), ("Tax by Account", [("account", "Account"), ("account_name", "Name")], None),
    ("Tax by Cost Centre", [("cost_centre", "Cost centre")], None), ("Tax by Business Unit", [("business_unit", "Business unit")], None), ("Tax by Department", [("branch", "Branch / department")], None),
    ("Tax by Counterparty", [("party_type", "Party type"), ("party", "Party")], None), ("Tax by Transaction", [("source_doctype", "Document type"), ("source_name", "Document")], None),
    ("Tax Type Summary", [("tax_type", "Tax type")], None), ("Jurisdiction Tax Summary", [("jurisdiction", "Jurisdiction"), ("tax_type", "Tax type")], None),
    ("Company Tax Summary", [("tax_type", "Tax type"), ("tax_code", "Rule")], None), ("Group Tax Summary", [("jurisdiction", "Jurisdiction"), ("tax_type", "Tax type")], None),
    ("Tax Cost by Jurisdiction", [("jurisdiction", "Jurisdiction")], lambda r: r["section"] == "Output"), ("Tax Cost by Business Unit", [("business_unit", "Business unit")], lambda r: r["section"] == "Output"),
    ("Tax Cost by Department", [("branch", "Branch / department")], lambda r: r["section"] == "Output"), ("Tax Cost by Company", [("tax_type", "Tax type")], lambda r: r["section"] == "Output"),
    ("Tax Trend Analysis", [(month, "Month"), ("tax_type", "Tax type")], None), ("Tax Month-over-Month", [(month, "Month")], None), ("Tax Quarter-over-Quarter", [(quarter, "Quarter")], None),
]:
    pv(_n, None, _dims, _p)


# ----------------------------------------------------------------------------------------------------- registers from the ledger
def _reg(name, domain, pred, title=None, extra_cols=(), extra=None):
    def fn(c):
        cols = [("date", "Date", DT), ("tax_type", "Tax type", T), ("section", "Direction", T), ("source_doctype", "Document type", T), ("source_name", "Document", T), ("party", "Party", T), ("tax_code", "Rule", T),
                ("rate", "Rate %", P), ("net", "Taxable Amount", M), ("tax", "Tax", M)] + list(extra_cols)
        rows = []
        for r in c.facts():
            if pred(r):
                row = {k: r[k] for k in ("date", "tax_type", "source_doctype", "source_name", "party", "tax_code", "rate")}
                row.update(section="Payable-type" if r["section"] == "Output" else "Credit-type", net=f2(r["net"]), tax=f2(r["tax"]))
                if extra: row.update(extra(r))
                rows.append(row)
        return cols, rows
    return report(name, domain)(fn)


_reg("Non-Recoverable VAT Register", "VAT & GST", lambda r: VAT(r) and r["section"] == "Input" and r["recoverable_pct"] < 100, extra_cols=[("recoverable", "Recoverable", M), ("non_recoverable", "Not Recoverable", M)],
     extra=lambda r: {"recoverable": f2(r["tax"] * Decimal(str(r["recoverable_pct"])) / 100), "non_recoverable": f2(r["tax"] - r["tax"] * Decimal(str(r["recoverable_pct"])) / 100)})
_reg("Partial VAT Recovery Register", "VAT & GST", lambda r: VAT(r) and r["section"] == "Input" and 0 < r["recoverable_pct"] < 100, extra_cols=[("recoverable_pct", "Recoverable %", P)], extra=lambda r: {"recoverable_pct": r["recoverable_pct"]})
_reg("VAT Adjustment Register", "VAT & GST", lambda r: VAT(r) and (r["source_doctype"] in ("Journal Entry Voucher", "Tax Journal") or r["tax"] < 0))
_reg("VAT Credit and Debit Note Register", "VAT & GST", lambda r: VAT(r) and ("Return" in r["source_doctype"] or "Note" in r["source_doctype"] or r["tax"] < 0))
_reg("Backdated Transaction Register", "Security & Audit Trail", lambda r: r["created"] and (r["created"] - r["date"]).days > 30,
     extra_cols=[("created", "Entered on", DT), ("days_back", "Days backdated", I)], extra=lambda r: {"created": r["created"], "days_back": (r["created"] - r["date"]).days})
_reg("Missing Tax Data", "Data Quality & Continuous Controls", lambda r: r["tax_type"] == "(no rule)" or not r["jurisdiction"])
_reg("Tax Transaction Quality", "Data Quality & Continuous Controls", lambda r: r["net"] and r["rate"] and abs(float(r["tax"]) - float(r["net"]) * r["rate"] / 100) > max(0.05, abs(float(r["tax"])) * 0.01),
     extra_cols=[("expected", "Expected Tax", M), ("diff", "Difference", M)], extra=lambda r: {"expected": f2(float(r["net"]) * r["rate"] / 100), "diff": f2(float(r["tax"]) - float(r["net"]) * r["rate"] / 100)})
REG["VAT Exceptions and Variances"] = lambda c: REG["Tax Transaction Quality"](_vat_only(c)); DOMAIN["VAT Exceptions and Variances"] = "VAT & GST"
REG["Invalid Tax Data"] = REG["Tax Transaction Quality"]; DOMAIN["Invalid Tax Data"] = "Data Quality & Continuous Controls"


def _vat_only(c):
    c2 = Ctx(c.start, c.end, "VAT", c.jurisdiction, c.party); return c2


@report("VAT Inclusive and Exclusive Transactions", "VAT & GST")
def _incl(c):
    return pivot([r for r in c.facts() if VAT(r)], [("inclusive", "Rule is tax inclusive")])


@report("VAT Recoverability Analysis", "VAT & GST")
def _recov(c):
    agg = defaultdict(lambda: [ZERO, ZERO])
    for r in c.facts():
        if VAT(r) and r["section"] == "Input":
            a = agg[(r["tax_code"], r["recoverable_pct"])]; a[0] += r["net"]; a[1] += r["tax"]
    cols = [("code", "Rule", T), ("pct", "Recoverable %", P), ("net", "Taxable Amount", M), ("tax", "Input Tax", M), ("rec", "Recoverable", M), ("non", "Not Recoverable", M)]
    return cols, [{"code": k[0], "pct": k[1], "net": f2(v[0]), "tax": f2(v[1]), "rec": f2(v[1] * Decimal(str(k[1])) / 100), "non": f2(v[1] - v[1] * Decimal(str(k[1])) / 100)} for k, v in sorted(agg.items())]


def monthly_net(c, kind):
    by = defaultdict(lambda: [ZERO, ZERO])
    for r in c.facts():
        if r["tax_type"] == kind:
            by[month(r["date"])][0 if r["section"] == "Output" else 1] += r["tax"]
    return by


@report("VAT Payable and Receivable", "VAT & GST")
def _vatpr(c):
    cols = [("m", "Month", T), ("out", "Output VAT", M), ("inp", "Input VAT", M), ("pay", "Payable", M), ("rec", "Receivable (credit)", M), ("cum", "Cumulative position", M)]
    rows, cum = [], ZERO
    for m, (o, i) in sorted(monthly_net(c, "VAT").items()):
        cum += o - i
        rows.append({"m": m, "out": f2(o), "inp": f2(i), "pay": f2(max(o - i, 0)), "rec": f2(max(i - o, 0)), "cum": f2(cum)})
    return cols, rows


@report("VAT Credit Balance", "VAT & GST")
def _vatcb(c):
    cols, rows = _vatpr(c)
    return cols, [r for r in rows if r["cum"] < 0]


@report("VAT Ledger Movement", "VAT & GST")
def _movement(c):
    accts = sorted({r["account"] for r in load_facts(date(2000, 1, 1), c.end) if r["tax_type"] == "VAT"})
    return account_movement(c, accts)


def account_movement(c, accts):
    r = get_table("Account Ledger Record"); a = get_table("Account")
    cols = [("account", "Account", T), ("name", "Name", T), ("opening", "Opening", M), ("debit", "Debits", M), ("credit", "Credits", M), ("closing", "Closing (debit +)", M)]
    rows = []
    with db.transaction() as conn:
        for acc in accts:
            q = select(r.c.posting_date, r.c.base_debit, r.c.base_credit).where(r.c.account == acc, r.c.posting_date <= c.end)
            op = dr = cr = ZERO
            for x in conn.execute(q).mappings():
                d = as_date(x["posting_date"])
                if d < c.start: op += _d(x["base_debit"]) - _d(x["base_credit"])
                else: dr += _d(x["base_debit"]); cr += _d(x["base_credit"])
            nm = conn.execute(select(a.c.account_name).where(a.c.name == acc)).scalar()
            rows.append({"account": acc, "name": nm, "opening": f2(op), "debit": f2(dr), "credit": f2(cr), "closing": f2(op + dr - cr)})
    return cols, rows


# ----------------------------------------------------------------------------------------------------- compliance and filing
def L(doctype, fields, filters=None, order=None, limit=2000):
    return get_list(doctype, filters=filters or [], fields=fields, order_by=order, limit=limit)


def _obl(c, extra=None):
    flt = []
    if c.tax_type: flt.append(["tax_type", "=", c.tax_type])
    if c.jurisdiction: flt.append(["jurisdiction", "=", c.jurisdiction])
    rows = L("Tax Obligation", ["name", "tax_type", "jurisdiction", "period_start", "period_end", "due_date", "status", "owner_user", "tax_return", "filing_reference", "evidence_reference", "overdue"], flt, "due_date asc")
    out = []
    for o in rows:
        due = as_date(o["due_date"]); o["due_date"] = due
        o["days"] = (due - c.today).days
        o["state"] = "Closed" if o["status"] in ("Filed", "Accepted", "Closed") else ("Overdue" if due < c.today else "Open")
        out.append(o)
    return out


OBL_COLS = [("name", "Obligation", T), ("tax_type", "Tax type", T), ("jurisdiction", "Jurisdiction", T), ("period_start", "From", DT), ("period_end", "To", DT), ("due_date", "Due", DT), ("days", "Days to due (negative = late)", I),
            ("status", "Status", T), ("owner_user", "Owner", T), ("tax_return", "Return", T), ("filing_reference", "Filing reference", T)]


@report("Tax Obligation Register", "Compliance & Filing")
def _obl_reg(c): return OBL_COLS, _obl(c)


@report("Upcoming Obligations", "Compliance & Filing")
def _upcoming(c): return OBL_COLS, [o for o in _obl(c) if o["state"] == "Open" and o["days"] <= 60]


@report("Overdue Obligations", "Compliance & Filing")
def _overdue(c):
    from velora_erp.tax import deadlines
    cols = OBL_COLS + [("tax", "Tax at stake", M), ("penalty", "Est. penalty", M), ("interest", "Est. interest", M), ("total", "Est. total exposure", M)]
    rows = []
    for o in _obl(c):
        if o["state"] == "Overdue":
            ex = deadlines.exposure(o, c.today); rows.append({**o, "tax": f2(ex["tax"]), "penalty": f2(ex["penalty"]), "interest": f2(ex["interest"]), "total": f2(ex["total"])})
    return cols, rows


for _alias, _src, _dom in (("Overdue Tax Payments", "Overdue Obligations", "Payments, Credits & Refunds"), ("Penalty Computation", "Overdue Obligations", "Audit, Assessment & Disputes"), ("Interest Computation", "Overdue Obligations", "Audit, Assessment & Disputes"),
                           ("Group Penalty Exposure", "Overdue Obligations", "Group & Executive Management"), ("Group Interest Exposure", "Overdue Obligations", "Group & Executive Management"),
                           ("Upcoming Tax Payments", "Upcoming Obligations", "Payments, Credits & Refunds"), ("At-Risk Work", "Upcoming Obligations", "Operations & Work Management")):
    REG[_alias] = REG[_src]; DOMAIN[_alias] = _dom


@report("Filing Evidence Register", "Compliance & Filing")
def _evidence(c):
    cols = [("name", "Obligation", T), ("tax_type", "Tax type", T), ("period_end", "Period end", DT), ("status", "Status", T), ("filing_reference", "Filing reference", T), ("evidence_reference", "Evidence", T), ("gap", "Gap", T)]
    return cols, [{**o, "gap": "" if o["evidence_reference"] else ("Filed without evidence" if o["status"] in ("Filed", "Accepted", "Closed") else "")} for o in _obl(c)]


REG["Filing Reference Register"] = _evidence; DOMAIN["Filing Reference Register"] = "Compliance & Filing"


def _returns(c):
    flt = []
    if c.tax_type: flt.append(["tax_type", "=", c.tax_type])
    if c.jurisdiction: flt.append(["jurisdiction", "=", c.jurisdiction])
    return L("Tax Return", ["name", "tax_type", "jurisdiction", "period_start", "period_end", "return_status", "approval_status", "docstatus", "output_tax", "input_tax", "non_recoverable_tax", "net_payable", "filing_reference", "acknowledgement", "amends", "approved_by", "calculated_on"], flt, "period_end desc")


RET_COLS = [("name", "Return", T), ("tax_type", "Tax type", T), ("jurisdiction", "Jurisdiction", T), ("period_start", "From", DT), ("period_end", "To", DT), ("return_status", "Status", T), ("approval_status", "Approval", T),
            ("output_tax", "Output / Payable-type", M), ("input_tax", "Input / Credit-type", M), ("non_recoverable_tax", "Not recoverable", M), ("net_payable", "Net payable", M), ("filing_reference", "Filing ref.", T), ("acknowledgement", "Acknowledgement", T), ("amends", "Amends", T)]


@report("Tax Return Register", "Compliance & Filing")
def _ret_reg(c): return RET_COLS, [{**r, "output_tax": f2(r["output_tax"]), "input_tax": f2(r["input_tax"]), "non_recoverable_tax": f2(r["non_recoverable_tax"]), "net_payable": f2(r["net_payable"])} for r in _returns(c)]


@report("Return Versions and Amendments", "Compliance & Filing")
def _ret_amend(c): return RET_COLS, [r for r in _ret_reg(c)[1] if r["amends"]]


REG["Resubmission Register"] = _ret_amend; DOMAIN["Resubmission Register"] = "Compliance & Filing"


@report("Return Rejections", "Compliance & Filing")
def _ret_rej(c): return RET_COLS, [r for r in _ret_reg(c)[1] if r["return_status"] == "Rejected" or r["approval_status"] == "Rejected"]


@report("Return Review Queue", "Compliance & Filing")
def _ret_q(c): return RET_COLS, [r for r in _ret_reg(c)[1] if r["approval_status"] == "Pending" or r["return_status"] in ("Draft", "Calculated")]


@report("Authority Acknowledgment Register", "Compliance & Filing")
def _ack(c): return RET_COLS, [r for r in _ret_reg(c)[1] if r["acknowledgement"] or r["return_status"] in ("Filed", "Accepted")]


@report("Tax Return Detail", "Compliance & Filing")
def _ret_detail(c):
    cols = [("ret", "Return", T), ("section", "Section", T), ("code", "Rule", T), ("rate", "Rate %", P), ("net", "Net amount", M), ("tax", "Tax", M), ("rec", "Recoverable", M), ("non", "Not recoverable", M)]
    rows = []
    for r in _returns(c)[:300]:
        d = get_doc("Tax Return", r["name"])
        for ln in d.lines or []:
            rows.append({"ret": r["name"], "section": ln.section, "code": ln.tax_code, "rate": ln.tax_rate, "net": f2(ln.net_amount), "tax": f2(ln.tax_amount), "rec": f2(ln.recoverable_amount), "non": f2(ln.non_recoverable_amount)})
    return cols, rows


REG["VAT Return Detail"] = _ret_detail; DOMAIN["VAT Return Detail"] = "VAT & GST"; REG["WHT Return Detail"] = _ret_detail; DOMAIN["WHT Return Detail"] = "WHT"


@report("VAT Return Line Reconciliation", "VAT & GST")
def _ret_recon(c):
    cols = [("ret", "Return", T), ("code", "Rule", T), ("section", "Section", T), ("ret_tax", "Per return", M), ("led_tax", "Per ledger now", M), ("diff", "Difference", M), ("note", "Note", T)]
    rows = []
    for r in _returns(c)[:100]:
        if c.tax_type and r["tax_type"] != c.tax_type: continue
        d = get_doc("Tax Return", r["name"])
        led = defaultdict(lambda: ZERO)
        for f in load_facts(as_date(r["period_start"]), as_date(r["period_end"])):
            led[(f["section"], f["tax_code"])] += f["tax"]
        for ln in d.lines or []:
            key = ("Output" if ln.section == "Output tax" else "Input", ln.tax_code)
            now = led.get(key, ZERO); diff = _d(ln.tax_amount) - now
            rows.append({"ret": r["name"], "code": ln.tax_code, "section": ln.section, "ret_tax": f2(ln.tax_amount), "led_tax": f2(now), "diff": f2(diff), "note": "Ledger moved since the return" if abs(diff) > Decimal("0.005") else "Agrees"})
    return cols, rows


@report("Compliance Scorecard", "Compliance & Filing")
def _score(c):
    cols = [("group", "Group", T), ("total", "Obligations", I), ("closed", "Filed / closed", I), ("open", "Open", I), ("overdue", "Overdue", I), ("pct", "On-track %", P)]
    return cols, _score_rows(_obl(c), lambda o: "All")


def _score_rows(obls, keyf):
    g = defaultdict(lambda: {"total": 0, "closed": 0, "open": 0, "overdue": 0})
    for o in obls:
        a = g[keyf(o) or "(none)"]; a["total"] += 1; a[{"Closed": "closed", "Open": "open", "Overdue": "overdue"}[o["state"]]] += 1
    return [{"group": k, **a, "pct": round(100 * (a["total"] - a["overdue"]) / a["total"], 1) if a["total"] else 0} for k, a in sorted(g.items())]


def _jur_authority():
    return {j["name"]: j["authority"] for j in L("Tax Jurisdiction", ["name", "authority"])}


@report("Compliance by Tax Type", "Compliance & Filing")
def _c_type(c): return _score(c)[0], _score_rows(_obl(c), lambda o: o["tax_type"])


@report("Compliance by Authority", "Compliance & Filing")
def _c_auth(c):
    a = _jur_authority(); return _score(c)[0], _score_rows(_obl(c), lambda o: a.get(o["jurisdiction"]) or o["jurisdiction"])


@report("Compliance by Owner", "Compliance & Filing")
def _c_owner(c): return _score(c)[0], _score_rows(_obl(c), lambda o: o["owner_user"] or "(unassigned)")


@report("Compliance Trend", "Compliance & Filing")
def _c_trend(c): return _score(c)[0], _score_rows(_obl(c), lambda o: month(o["due_date"]))


REG["Group Compliance Summary"] = _c_type; DOMAIN["Group Compliance Summary"] = "Group & Executive Management"


@report("Tax Work Queue", "Operations & Work Management")
def _queue(c):
    cols = [("kind", "Document", T), ("name", "Name", T), ("what", "What is waiting", T), ("when", "Date", DT), ("owner", "Owner", T)]
    rows = []
    for dt, label in (("Tax Journal", "posting_date"), ("Income Tax Computation", "period_end"), ("Tax Return", "period_end"), ("Tax Rule", "effective_from")):
        for r in L(dt, ["name", label, "owner", "approval_status"], [["docstatus", "=", 0]]):
            rows.append({"kind": dt, "name": r["name"], "what": f"Draft - approval {r['approval_status']}", "when": as_date(r[label]), "owner": r.get("owner")})
    for o in _obl(c):
        if o["state"] != "Closed": rows.append({"kind": "Tax Obligation", "name": o["name"], "what": f"{o['tax_type']} {o['state'].lower()} - due {o['due_date']}", "when": o["due_date"], "owner": o["owner_user"] or "(unassigned)"})
    return cols, sorted(rows, key=lambda r: str(r["when"]))


@report("My Tax Work", "Operations & Work Management")
def _mine(c):
    from velora.permissions import get_session
    u = get_session().user; cols, rows = _queue(c); return cols, [r for r in rows if r["owner"] == u]


@report("Unassigned Work", "Operations & Work Management")
def _unass(c):
    cols, rows = _queue(c); return cols, [r for r in rows if r["owner"] in ("(unassigned)", None, "")]


@report("Tax Jurisdiction Register", "International Tax & Transfer Pricing")
def _jur(c):
    cols = [("name", "Jurisdiction", T), ("jurisdiction_name", "Name", T), ("country_code", "Country", T), ("level", "Level", T), ("authority", "Authority", T), ("currency", "Currency", T), ("enabled", "Enabled", I)]
    return cols, L("Tax Jurisdiction", [x[0] for x in cols])


# ----------------------------------------------------------------------------------------------------- liabilities, payments, credits
ACCRUING = {"Sales Invoice", "Purchase Invoice", "Sales Return", "Purchase Return", "Tax Journal", "Investment Transaction", "Investment", "Expense Batch"}


def tax_accounts(kind=None, root=None):
    """{account: (name, tax_type)} for accounts that carry tax-coded lines, anywhere in history."""
    out = {}
    for r in load_facts(date(2000, 1, 1), date(2100, 1, 1)):
        if (not kind or r["tax_type"] == kind) and (not root or ("Output" if root == "Liability" else "Input") == r["section"]):
            out[r["account"]] = (r["account_name"], r["tax_type"])
    return out


def ledger_on(accts, start, end):
    r = get_table("Account Ledger Record")
    if not accts: return []
    with db.transaction() as conn:
        q = select(r.c.posting_date, r.c.account, r.c.source_doctype, r.c.source_name, r.c.party, r.c.base_debit, r.c.base_credit, r.c.line_description).where(r.c.account.in_(list(accts)), r.c.posting_date >= start, r.c.posting_date <= end).order_by(r.c.posting_date)
        return [dict(x) for x in conn.execute(q).mappings()]


def _payments(c, kind=None):
    accts = tax_accounts(kind, "Liability")
    cols = [("date", "Date", DT), ("tax_type", "Tax type", T), ("account", "Account", T), ("source_doctype", "Document type", T), ("source_name", "Document", T), ("party", "Party", T), ("amount", "Paid / remitted", M), ("note", "Description", T)]
    rows = [{"date": as_date(x["posting_date"]), "tax_type": accts[x["account"]][1], "account": x["account"], "source_doctype": x["source_doctype"], "source_name": x["source_name"], "party": x["party"], "amount": f2(x["base_debit"]), "note": x["line_description"]}
            for x in ledger_on(accts, c.start, c.end) if _d(x["base_debit"]) > 0 and x["source_doctype"] not in ACCRUING]
    return cols, rows


@report("Tax Payments Register", "Payments, Credits & Refunds")
def _pay_all(c): return _payments(c, c.tax_type)


for _n, _k, _d_ in (("VAT Payment Register", "VAT", "VAT & GST"), ("WHT Remittance Register", "WHT", "WHT")):
    REG[_n] = (lambda k: (lambda c: _payments(c, k)))(_k); DOMAIN[_n] = _d_
for _n, _d_ in (("Tax Settlement Register", "Payments, Credits & Refunds"), ("Group Tax Payments", "Group & Executive Management"), ("Tax Payment Gateway Status", None)):
    if _d_: REG[_n] = _pay_all; DOMAIN[_n] = _d_


@report("Tax Liability Register", "Payments, Credits & Refunds")
def _liab(c):
    accts = tax_accounts(c.tax_type, "Liability")
    cols = [("tax_type", "Tax type", T), ("account", "Account", T), ("name", "Name", T), ("opening", "Opening liability", M), ("accrued", "Accrued in period", M), ("paid", "Paid in period", M), ("closing", "Closing liability", M)]
    rows = []
    for acc, (nm, kind) in sorted(accts.items(), key=lambda kv: kv[1][1]):
        op = acc_ = paid = ZERO
        for x in ledger_on([acc], date(2000, 1, 1), c.end):
            d = as_date(x["posting_date"]); net = _d(x["base_credit"]) - _d(x["base_debit"])
            if d < c.start: op += net
            else:
                acc_ += _d(x["base_credit"]) if x["source_doctype"] in ACCRUING or _d(x["base_credit"]) else ZERO
                paid += _d(x["base_debit"])
        rows.append({"tax_type": kind, "account": acc, "name": nm, "opening": f2(op), "accrued": f2(acc_), "paid": f2(paid), "closing": f2(op + acc_ - paid)})
    return cols, rows


for _n, _d_ in (("Outstanding Tax Liability", "Payments, Credits & Refunds"), ("Group Tax Liability", "Group & Executive Management"), ("Group Outstanding Liability", "Group & Executive Management"), ("Tax Payment Reconciliation", "Payments, Credits & Refunds")):
    REG[_n] = _liab; DOMAIN[_n] = _d_


@report("Tax Liability by Authority", "Payments, Credits & Refunds")
def _liab_auth(c):
    auth = _jur_authority(); jur = {code: r.jurisdiction for code, r in rule_index().items()}
    by = defaultdict(lambda: ZERO)
    for r in c.facts():
        if r["section"] == "Output": by[auth.get(r["jurisdiction"]) or r["jurisdiction"] or "(none)"] += r["tax"]
    return [("a", "Authority", T), ("t", "Tax payable-type in period", M)], [{"a": k, "t": f2(v)} for k, v in sorted(by.items())]


@report("Tax Liability by Period", "Payments, Credits & Refunds")
def _liab_period(c):
    return pivot([r for r in c.facts() if r["section"] == "Output"], [(month, "Month"), ("tax_type", "Tax type")], sort="key")


@report("Tax Liability Aging", "Payments, Credits & Refunds")
def _liab_aging(c):
    buckets = [("Not yet due", None, 0), ("1-30 days", 1, 30), ("31-60 days", 31, 60), ("61-90 days", 61, 90), ("Over 90 days", 91, 10 ** 6)]
    rets = {r["name"]: r for r in _returns(c)}
    cols = [("tax_type", "Tax type", T)] + [(f"b{i}", b[0], M) for i, b in enumerate(buckets)] + [("total", "Total", M)]
    agg = defaultdict(lambda: [ZERO] * len(buckets))
    for o in _obl(c):
        if o["state"] == "Closed": continue
        amt = _d((rets.get(o["tax_return"]) or {}).get("net_payable"))
        if not amt:
            from velora_erp.tax import deadlines
            amt = deadlines.exposure({**o, "due_date": o["due_date"]}, c.today)["tax"] if o["days"] < 0 else _est_obl(o)
        late = -o["days"]
        i = 0 if late <= 0 else next(k for k, b in enumerate(buckets) if k and b[1] <= late <= b[2])
        agg[o["tax_type"]][i] += amt
    return cols, [{"tax_type": k, **{f"b{i}": f2(v) for i, v in enumerate(vs)}, "total": f2(sum(vs))} for k, vs in sorted(agg.items())]


def _est_obl(o):
    kind = o["tax_type"]; tot = ZERO
    for f in load_facts(as_date(o["period_start"]), as_date(o["period_end"])):
        if f["tax_type"] == kind: tot += f["tax"] if f["section"] == "Output" else (-f["tax"] if kind != "WHT" else ZERO)
    return max(tot, ZERO)


@report("Tax Cash Flow Forecast", "Payments, Credits & Refunds")
def _cash_fc(c):
    cols = [("m", "Month due", T), ("tax_type", "Tax type", T), ("amount", "Expected payment", M), ("basis", "Basis", T)]
    rets = {r["name"]: r for r in _returns(c)}
    rows = []
    for o in _obl(c):
        if o["state"] == "Closed": continue
        r = rets.get(o["tax_return"])
        amt, basis = (_d(r["net_payable"]), "Calculated return") if r and _d(r["net_payable"]) else (_est_obl(o), "Estimate from the ledger")
        rows.append({"m": month(o["due_date"]), "tax_type": o["tax_type"], "amount": f2(amt), "basis": basis})
    return cols, sorted(rows, key=lambda r: (r["m"], r["tax_type"]))


for _n, _d_ in (("Tax Liability Forecast", "Planning & Forecasting"), ("Tax Payment Forecast", "Planning & Forecasting"), ("Group Tax Cash Flow", "Group & Executive Management")):
    REG[_n] = _cash_fc; DOMAIN[_n] = _d_


def _credits(c):
    accts = tax_accounts(None, "Asset")
    return accts


@report("Tax Credit Movement", "Payments, Credits & Refunds")
def _credit_mv(c):
    cols, rows = account_movement(c, sorted(_credits(c)))
    kinds = _credits(c)
    for r in rows: r["name"] = f"{r['name']} ({kinds[r['account']][1]})"
    return cols, rows


for _n, _d_ in (("Unutilized Tax Credits", "Payments, Credits & Refunds"), ("Group Tax Credits", "Group & Executive Management"), ("WHT Credit Register", "WHT")):
    REG[_n] = _credit_mv; DOMAIN[_n] = _d_


@report("Tax Credit Aging", "Payments, Credits & Refunds")
def _credit_aging(c):
    buckets = [("0-90 days", 0, 90), ("91-180 days", 91, 180), ("181-365 days", 181, 365), ("Over 1 year", 366, 10 ** 6)]
    agg = defaultdict(lambda: [ZERO] * len(buckets))
    for r in load_facts(date(2000, 1, 1), c.end):
        if r["section"] == "Input" and (not c.tax_type or r["tax_type"] == c.tax_type):
            age = (c.end - r["date"]).days
            i = next(k for k, b in enumerate(buckets) if b[1] <= age <= b[2]); agg[r["tax_type"]][i] += r["tax"]
    cols = [("tax_type", "Tax type", T)] + [(f"b{i}", b[0], M) for i, b in enumerate(buckets)] + [("total", "Total credits raised", M)]
    return cols, [{"tax_type": k, **{f"b{i}": f2(v) for i, v in enumerate(vs)}, "total": f2(sum(vs))} for k, vs in sorted(agg.items())]


REG["WHT Credit Aging"] = lambda c: _credit_aging(Ctx(c.start, c.end, "WHT", c.jurisdiction, c.party)); DOMAIN["WHT Credit Aging"] = "WHT"


@report("Authority Account Statement", "Payments, Credits & Refunds")
def _auth_stmt(c):
    cols = [("date", "Date", DT), ("tax_type", "Tax type", T), ("what", "Entry", T), ("source", "Document", T), ("charge", "Tax charged (payable)", M), ("paid", "Paid / remitted", M), ("balance", "Running balance owed", M)]
    accts = tax_accounts(c.tax_type, "Liability")
    rows, bal = [], ZERO
    for x in ledger_on(accts, date(2000, 1, 1), c.end):
        d = as_date(x["posting_date"]); cr, dr = _d(x["base_credit"]), _d(x["base_debit"]); bal += cr - dr
        if d >= c.start: rows.append({"date": d, "tax_type": accts[x["account"]][1], "what": "Tax charged" if cr > dr else "Payment / remittance", "source": f"{x['source_doctype']} {x['source_name']}", "charge": f2(cr), "paid": f2(dr), "balance": f2(bal)})
    return cols, rows


REG["Authority Statement Reconciliation"] = _liab; DOMAIN["Authority Statement Reconciliation"] = "Payments, Credits & Refunds"


# ----------------------------------------------------------------------------------------------------- withholding tax from Tax Journals
def _journal_rows(c):
    h, l = get_table("Tax Journal"), get_table("Tax Journal Line")
    q = (select(h.c.name, h.c.posting_date, l.c.party_type, l.c.party, l.c.party_name, l.c.nature, l.c.payee_class, l.c.invoice_reference, l.c.tax_rule, l.c.rate, l.c.gross_amount, l.c.wht_amount, l.c.certificate_number, l.c.certificate_date)
         .join(l, l.c.parent == h.c.name).where(h.c.docstatus == 1, h.c.posting_date >= c.start, h.c.posting_date <= c.end))
    with db.transaction() as conn:
        return [dict(x) for x in conn.execute(q.order_by(h.c.posting_date)).mappings()]


@report("WHT Certificate Verification", "WHT")
def _cert(c):
    cols = [("name", "Tax Journal", T), ("posting_date", "Date", DT), ("party_type", "Type", T), ("party_name", "Party", T), ("wht_amount", "Tax withheld", M), ("certificate_number", "Certificate", T), ("certificate_date", "Certificate date", DT), ("status", "Status", T)]
    rows = []
    for x in _journal_rows(c):
        d = as_date(x["posting_date"]); cd = as_date(x["certificate_date"])
        st = "Missing certificate" if not x["certificate_number"] else ("Certificate dated before the payment by over a year" if cd and (d - cd).days > 365 else ("No certificate date" if not cd else "Complete"))
        rows.append({**{k: x[k] for k, _l, _t in cols if k in x}, "wht_amount": f2(x["wht_amount"]), "status": st})
    return cols, rows


for _n, _d_ in (("WHT Certificate Received Register", "WHT"), ("WHT Certificate Issued Register", "WHT")):
    REG[_n] = (lambda issued: (lambda c: (_cert(c)[0], [r for r in _cert(c)[1] if (r["party_type"] in ("Supplier", "Payment made")) == issued])))(_n.endswith("Issued Register")); DOMAIN[_n] = _d_
REG["WHT Certificate Expiry"] = lambda c: (_cert(c)[0], [r for r in _cert(c)[1] if r["status"] != "Complete"]); DOMAIN["WHT Certificate Expiry"] = "WHT"


@report("WHT Exceptions", "WHT")
def _wht_exc(c):
    cols = [("name", "Tax Journal", T), ("party_name", "Party", T), ("issue", "Exception", T), ("wht_amount", "Tax withheld", M), ("expected", "Expected from rule", M)]
    rules = rule_index(); rows = []
    for x in _journal_rows(c):
        rule = rules.get((x["tax_rule"] or "").upper()); exp = _d(x["gross_amount"]) * (rule.rate / 100 if rule else 0)
        issues = []
        if not x["certificate_number"]: issues.append("No certificate number")
        if rule and abs(exp - _d(x["wht_amount"])) > Decimal("0.05"): issues.append("Amount differs from the rule rate")
        if not x["tax_rule"]: issues.append("No WHT rule applied")
        for i in issues: rows.append({"name": x["name"], "party_name": x["party_name"], "issue": i, "wht_amount": f2(x["wht_amount"]), "expected": f2(exp) if rule else None})
    return cols, rows


@report("WHT Credit Utilization", "WHT")
def _wht_util(c):
    cols = [("name", "Computation", T), ("period_end", "Period end", DT), ("avail", "Credits available", M), ("used", "Credits used", M), ("left", "Unused", M)]
    rows = [{"name": r["name"], "period_end": as_date(r["period_end"]), "avail": f2(r["wht_available"]), "used": f2(r["wht_utilised"]), "left": f2(_d(r["wht_available"]) - _d(r["wht_utilised"]))}
            for r in L("Income Tax Computation", ["name", "period_end", "wht_available", "wht_utilised"], [["docstatus", "=", 1]], "period_end desc")]
    return cols, rows


REG["Tax Credit Utilization"] = _wht_util; DOMAIN["Tax Credit Utilization"] = "Payments, Credits & Refunds"; REG["Tax Credit Register"] = _wht_util; DOMAIN["Tax Credit Register"] = "CIT & Tax Computation"
REG["WHT Unutilized Credits"] = _credit_mv; DOMAIN["WHT Unutilized Credits"] = "WHT"


@report("WHT Remittance Reconciliation", "WHT")
def _wht_recon(c):
    return _recon(c, "WHT")


@report("VAT Reconciliation", "VAT & GST")
def _vat_recon(c):
    return _recon(c, "VAT")


def _recon(c, kind):
    cols = [("what", "Item", T), ("amount", "Amount", M), ("note", "Note", T)]
    c2 = Ctx(c.start, c.end, kind, c.jurisdiction)
    out = sum((r["tax"] for r in c2.facts() if r["section"] == "Output"), ZERO); inp = sum((r["tax"] for r in c2.facts() if r["section"] == "Input"), ZERO)
    paid = sum((_d(r["amount"]) for r in _payments(c2, kind)[1]), ZERO)
    rets = [r for r in _returns(c2) if r["tax_type"] == kind and r["docstatus"] == 1 and as_date(r["period_end"]) >= c.start and as_date(r["period_start"]) <= c.end]
    ret_net = sum((_d(r["net_payable"]) for r in rets), ZERO)
    net = out - inp if kind != "WHT" else out
    rows = [{"what": "Tax payable-type per ledger", "amount": f2(out), "note": "Output / withheld by us"}]
    if kind != "WHT": rows.append({"what": "Less: credit-type per ledger", "amount": f2(-inp), "note": "Input tax"})
    rows += [{"what": "Net due per ledger", "amount": f2(net), "note": ""}, {"what": "Net payable per submitted returns", "amount": f2(ret_net), "note": f"{len(rets)} return(s)"},
             {"what": "Difference (ledger - returns)", "amount": f2(net - ret_net), "note": "Should be nil once every period is returned" if abs(net - ret_net) > Decimal("0.005") else "Agrees"},
             {"what": "Paid / remitted in period", "amount": f2(paid), "note": ""}, {"what": "Still to pay (ledger due - paid)", "amount": f2(net - paid), "note": ""}]
    return cols, rows


REG["Tax Payment Reconciliation"] = lambda c: _recon(c, c.tax_type or "VAT"); DOMAIN["Tax Payment Reconciliation"] = "Payments, Credits & Refunds"


# ----------------------------------------------------------------------------------------------------- company income tax
def _cits(c, approved=True):
    flt = [["docstatus", "=", 1]] if approved else [["docstatus", "in", [0, 1]]]
    return L("Income Tax Computation", ["name", "period_start", "period_end", "jurisdiction", "income_tax_rule", "minimum_tax_rule", "levy_rules", "turnover", "total_expenses", "accounting_profit", "total_add_backs", "total_deductions",
                                        "total_capital_allowances", "adjusted_profit", "loss_brought_forward", "loss_relieved", "assessable_profit", "loss_carried_forward", "income_tax", "minimum_tax", "income_tax_charge", "levies",
                                        "wht_available", "wht_utilised", "net_payable", "docstatus"], flt, "period_end desc")


def _cit_cols(*names):
    lab = {"turnover": "Turnover", "total_expenses": "Expenses", "accounting_profit": "Profit per books", "total_add_backs": "Add backs", "total_deductions": "Deductions", "total_capital_allowances": "Capital allowances",
           "adjusted_profit": "Adjusted profit", "loss_brought_forward": "Loss b/f", "loss_relieved": "Loss relieved", "assessable_profit": "Assessable profit", "loss_carried_forward": "Loss c/f", "income_tax": "Income tax",
           "minimum_tax": "Minimum tax", "income_tax_charge": "Tax charged", "levies": "Levies", "wht_available": "WHT credits available", "wht_utilised": "WHT credits used", "net_payable": "Net payable"}
    return [("name", "Computation", T), ("period_end", "Period end", DT)] + [(n, lab[n], M) for n in names]


def _cit_rows(c, names, approved=True):
    return [{"name": r["name"], "period_end": as_date(r["period_end"]), **{n: f2(r[n]) for n in names}} for r in _cits(c, approved)]


def cit_report(name, domain, names, approved=True):
    REG[name] = (lambda cols, ap: (lambda c: (_cit_cols(*cols), _cit_rows(c, cols, ap))))(names, approved); DOMAIN[name] = domain


cit_report("Taxable Income Summary", "CIT & Tax Computation", ["accounting_profit", "total_add_backs", "total_deductions", "total_capital_allowances", "adjusted_profit", "assessable_profit"])
cit_report("Loss Carryforward Register", "CIT & Tax Computation", ["loss_brought_forward", "adjusted_profit", "loss_relieved", "loss_carried_forward"])
cit_report("Loss Utilization", "CIT & Tax Computation", ["loss_brought_forward", "loss_relieved", "loss_carried_forward"])
cit_report("Minimum Tax Analysis", "CIT & Tax Computation", ["turnover", "income_tax", "minimum_tax", "income_tax_charge"])
cit_report("CIT Provision", "CIT & Tax Computation", ["assessable_profit", "income_tax_charge", "levies", "wht_utilised", "net_payable"], approved=False)
cit_report("Current Tax Provision", "Tax Accounting & Financial Disclosure", ["assessable_profit", "income_tax_charge", "levies", "wht_utilised", "net_payable"], approved=False)
cit_report("Tax Expense Analysis", "Tax Accounting & Financial Disclosure", ["accounting_profit", "income_tax_charge", "levies", "wht_utilised", "net_payable"])
cit_report("Capital Allowance Register", "CIT & Tax Computation", ["total_capital_allowances", "adjusted_profit"])


@report("CIT Rate and Levy Analysis", "CIT & Tax Computation")
def _cit_rate(c):
    rules = rule_index()
    cols = [("name", "Computation", T), ("period_end", "Period end", DT), ("rule", "Income tax rule", T), ("rate", "Rate", T), ("levy_rules", "Levy rules", T), ("assessable_profit", "Assessable profit", M), ("income_tax", "Income tax", M), ("levies", "Levies", M), ("eff", "Income tax + levies as % of assessable", P)]
    rows = []
    for r in _cits(c):
        rule = rules.get((r["income_tax_rule"] or "").upper()); base = _d(r["assessable_profit"])
        rows.append({"name": r["name"], "period_end": as_date(r["period_end"]), "rule": r["income_tax_rule"], "rate": (f"{rule.rate}%" if rule and rule.method == "percentage" else (rule.method if rule else "")), "levy_rules": r["levy_rules"],
                     "assessable_profit": f2(base), "income_tax": f2(r["income_tax"]), "levies": f2(r["levies"]), "eff": round(float((_d(r["income_tax"]) + _d(r["levies"])) / base * 100), 2) if base else 0})
    return cols, rows


def _lines(c, sections):
    cols = [("comp", "Computation", T), ("period_end", "Period end", DT), ("section", "Section", T), ("description", "Description", T), ("account", "Account", T), ("book", "Amount in books", M), ("amount", "Tax adjustment", M), ("source", "Source", T)]
    rows = []
    for r in _cits(c, approved=False)[:60]:
        d = get_doc("Income Tax Computation", r["name"])
        for ln in d.lines or []:
            if not sections or ln.section in sections:
                rows.append({"comp": r["name"], "period_end": as_date(r["period_end"]), "section": ln.section, "description": ln.description, "account": ln.account, "book": f2(ln.book_amount), "amount": f2(ln.amount), "source": ln.source})
    return cols, rows


REG["Tax Adjustment Register"] = lambda c: _lines(c, None); DOMAIN["Tax Adjustment Register"] = "CIT & Tax Computation"
REG["Capital Allowance Computation"] = lambda c: _lines(c, {"Capital allowance"}); DOMAIN["Capital Allowance Computation"] = "CIT & Tax Computation"


@report("Profit to Taxable Profit Bridge", "CIT & Tax Computation")
def _bridge(c):
    rows_ = _cits(c, approved=False)
    cols = [("step", "Step", T), ("amount", "Amount", M), ("running", "Running total", M)]
    if not rows_: return cols, []
    r = rows_[0]
    steps = [("Profit per books", _d(r["accounting_profit"])), ("Add: expenses not tax allowed / partly / capital", _d(r["total_add_backs"])), ("Less: exempt income and deductions", -_d(r["total_deductions"])),
             ("Less: capital allowances", -_d(r["total_capital_allowances"])), ("Less: losses relieved", -_d(r["loss_relieved"]))]
    run, out = ZERO, []
    for s_, a in steps: run += a; out.append({"step": s_, "amount": f2(a), "running": f2(run)})
    out.append({"step": f"Assessable profit ({r['name']})", "amount": f2(r["assessable_profit"]), "running": f2(r["assessable_profit"])})
    return cols, out


@report("Allowable Expense Analysis", "CIT & Tax Computation")
def _allowable(c):
    from velora_erp.tax.cit import profit_and_loss
    cols = [("account", "Account", T), ("name", "Name", T), ("treatment", "Tax treatment", T), ("pct", "Not allowed %", P), ("net", "Expense in period", M), ("allowed", "Allowed", M), ("disallowed", "Not allowed", M)]
    rows = []
    for x in profit_and_loss(c.start, c.end):
        if x["root_type"] != "Expense": continue
        dis = x["net"] if x["treatment"] in ("Not tax allowed", "Capital (use capital allowance)") else x["net"] * x["percent"] / 100 if x["treatment"] == "Partly allowable" else ZERO
        rows.append({"account": x["account"], "name": x["name"], "treatment": x["treatment"], "pct": float(x["percent"]), "net": f2(x["net"]), "allowed": f2(x["net"] - dis), "disallowed": f2(dis)})
    return cols, rows


@report("CIT Return Reconciliation", "CIT & Tax Computation")
def _cit_ret(c):
    cols = [("name", "Computation", T), ("period_end", "Period end", DT), ("net_payable", "Net payable per computation", M), ("ret", "Income tax return", T), ("ret_net", "Net payable per return", M), ("diff", "Difference", M)]
    rets = [r for r in _returns(c) if r["tax_type"] == "Income Tax"]
    rows = []
    for r in _cits(c):
        m = next((x for x in rets if as_date(x["period_end"]) == as_date(r["period_end"])), None)
        rows.append({"name": r["name"], "period_end": as_date(r["period_end"]), "net_payable": f2(r["net_payable"]), "ret": m["name"] if m else "(no return yet)", "ret_net": f2(m["net_payable"]) if m else None, "diff": f2(_d(r["net_payable"]) - _d(m["net_payable"])) if m else None})
    return cols, rows


@report("Effective Tax Rate Analysis", "Tax Accounting & Financial Disclosure")
def _etr(c):
    cols = [("name", "Computation", T), ("period_end", "Period end", DT), ("profit", "Profit per books", M), ("charge", "Income tax + levies", M), ("etr", "Effective rate %", P), ("stat", "Rate on assessable %", P)]
    rows = []
    for r in _cits(c):
        p, ch = _d(r["accounting_profit"]), _d(r["income_tax_charge"]) + _d(r["levies"])
        a = _d(r["assessable_profit"])
        rows.append({"name": r["name"], "period_end": as_date(r["period_end"]), "profit": f2(p), "charge": f2(ch), "etr": round(float(ch / p * 100), 2) if p > 0 else None, "stat": round(float(ch / a * 100), 2) if a > 0 else None})
    return cols, rows


for _n in ("Tax vs Profit Analysis", "Tax to Profit Ratio", "Group Effective Tax Rate", "Tax Effective Rate"):
    REG[_n] = _etr; DOMAIN[_n] = "Analytics & AI" if _n.startswith("Tax ") else "Group & Executive Management"


@report("ETR Reconciliation", "Tax Accounting & Financial Disclosure")
def _etr_rec(c):
    rows_ = _cits(c)
    cols = [("item", "Item", T), ("amount", "Amount", M), ("rate", "% of profit per books", P)]
    if not rows_: return cols, []
    r = rows_[0]; rule = rule_index().get((r["income_tax_rule"] or "").upper()); p = _d(r["accounting_profit"])
    rate = rule.rate if rule and rule.method == "percentage" else ZERO
    items = [("Tax at the standard rate on profit per books", p * rate / 100), ("Effect of add-backs", _d(r["total_add_backs"]) * rate / 100), ("Effect of deductions and exempt income", -_d(r["total_deductions"]) * rate / 100),
             ("Effect of capital allowances", -_d(r["total_capital_allowances"]) * rate / 100), ("Effect of losses relieved", -_d(r["loss_relieved"]) * rate / 100), ("Minimum tax / other (balancing)", None),
             ("Levies", _d(r["levies"])), ("Total income tax and levies charged", _d(r["income_tax_charge"]) + _d(r["levies"]))]
    known = sum((a for _, a in items[:5] if a is not None), ZERO) + _d(r["levies"])
    out = []
    for lab, a in items:
        if a is None: a = _d(r["income_tax_charge"]) + _d(r["levies"]) - known
        out.append({"item": lab if lab.startswith("Total") else f"{lab} ({r['name']})" if lab.startswith("Tax at") else lab, "amount": f2(a), "rate": round(float(a / p * 100), 2) if p else None})
    return cols, out


# ----------------------------------------------------------------------------------------------------- deferred tax (from Deferred Tax Assessments)
def _dta_lines(c):
    rows = []
    for a in L("Deferred Tax Assessment", ["name", "assessment_date", "status"], [["docstatus", "in", [0, 1]]], "assessment_date desc", 20)[:1]:
        d = get_doc("Deferred Tax Assessment", a["name"])
        for ln in d.lines or []:
            rows.append({"assessment": a["name"], "date": as_date(a["assessment_date"]), "description": ln.description, "source": ln.source_type, "ref": ln.source_reference, "carrying": f2(ln.financial_carrying_amount),
                         "base": f2(ln.tax_base), "diff": f2(ln.temporary_difference), "kind": ln.difference_type, "rate": ln.tax_rate, "gross": f2(ln.gross_deferred_tax), "recognised": f2(ln.recognised_deferred_tax), "recognise": ln.recognise_deferred_tax_asset})
    return rows


DT_COLS = [("assessment", "Assessment", T), ("date", "Date", DT), ("description", "Description", T), ("source", "Source", T), ("ref", "Reference", T), ("carrying", "Carrying amount", M), ("base", "Tax base", M), ("diff", "Temporary difference", M),
           ("kind", "Type", T), ("rate", "Rate %", P), ("gross", "Deferred tax before recognition", M), ("recognised", "Recognised", M)]


@report("Temporary Difference Register", "Tax Accounting & Financial Disclosure")
def _td(c): return DT_COLS, _dta_lines(c)


REG["Tax Base Register"] = _td; DOMAIN["Tax Base Register"] = "Tax Accounting & Financial Disclosure"; REG["Deferred Tax Provision"] = _td; DOMAIN["Deferred Tax Provision"] = "Tax Accounting & Financial Disclosure"


@report("DTL Register", "Tax Accounting & Financial Disclosure")
def _dtl(c): return DT_COLS, [r for r in _dta_lines(c) if _d(r["diff"]) > 0]


@report("DTA Register", "Tax Accounting & Financial Disclosure")
def _dta(c): return DT_COLS, [r for r in _dta_lines(c) if _d(r["diff"]) < 0]


@report("Unrecognized DTA Register", "Tax Accounting & Financial Disclosure")
def _undta(c): return DT_COLS, [r for r in _dta_lines(c) if _d(r["diff"]) < 0 and not r["recognise"]]


REG["DTA Recognition Analysis"] = _dta; DOMAIN["DTA Recognition Analysis"] = "Tax Accounting & Financial Disclosure"


@report("Deferred Tax by Category", "Tax Accounting & Financial Disclosure")
def _dt_cat(c):
    g = defaultdict(lambda: [ZERO, ZERO])
    for r in _dta_lines(c): a = g[r["source"] or "(none)"]; a[0] += _d(r["diff"]); a[1] += _d(r["recognised"])
    return [("k", "Source", T), ("d", "Temporary difference", M), ("r", "Deferred tax recognised", M)], [{"k": k, "d": f2(v[0]), "r": f2(v[1])} for k, v in sorted(g.items())]


# (registered below as Tax Provision Movement)
def _dt_mv(c):
    cols = [("name", "Assessment", T), ("date", "Date", DT), ("dta", "Deferred tax asset", M), ("dtl", "Deferred tax liability", M), ("prev", "Previous net liability", M), ("net", "Net liability", M), ("mv", "Movement", M)]
    return cols, [{"name": a["name"], "date": as_date(a["assessment_date"]), "dta": f2(a["deferred_tax_asset"]), "dtl": f2(a["deferred_tax_liability"]), "prev": f2(a["previous_net_liability"]), "net": f2(a["net_deferred_tax_liability"]), "mv": f2(a["movement"])}
                  for a in L("Deferred Tax Assessment", ["name", "assessment_date", "deferred_tax_asset", "deferred_tax_liability", "previous_net_liability", "net_deferred_tax_liability", "movement"], [["docstatus", "in", [0, 1]]], "assessment_date desc")]


REG["Tax Provision Movement"] = _dt_mv; DOMAIN["Tax Provision Movement"] = "Tax Accounting & Financial Disclosure"


# ----------------------------------------------------------------------------------------------------- trends, comparisons, forecasts, sensitivities
def _series(c, key, kind=None, start=None):
    g = defaultdict(lambda: [ZERO, ZERO])
    for r in c.facts(start or c.start, c.end):
        if not kind or r["tax_type"] == kind: g[key(r["date"])][0 if r["section"] == "Output" else 1] += r["tax"]
    return dict(sorted(g.items()))


def _compare(c, key, lag, label):
    ser = _series(c, key, c.tax_type, date(c.start.year - 2, 1, 1))
    cols = [("p", label, T), ("out", "Payable-type", M), ("inp", "Credit-type", M), ("net", "Net", M), ("prev", "Same measure, comparison period", M), ("chg", "Change", M), ("pct", "Change %", P)]
    keys = list(ser)
    rows = []
    for k in keys:
        if not (c.start <= as_date(k + "-01" if len(k) == 7 and "Q" not in k else (f"{k[:4]}-{(int(k[-1]) - 1) * 3 + 1:02d}-01" if "Q" in k else f"{k}-01-01")) <= c.end): continue
        o, i = ser[k]; net = o - i
        pk = lag(k); po, pi_ = ser.get(pk, (ZERO, ZERO)); prev = po - pi_
        rows.append({"p": k, "out": f2(o), "inp": f2(i), "net": f2(net), "prev": f2(prev) if pk in ser else None, "chg": f2(net - prev) if pk in ser else None, "pct": round(float((net - prev) / abs(prev) * 100), 1) if pk in ser and prev else None})
    return cols, rows


def _lag_month(k): y, m = map(int, k.split("-")); return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
def _lag_yoy_month(k): y, m = k.split("-"); return f"{int(y) - 1}-{m}"
def _lag_q(k): y, q = k.split("-Q"); y, q = int(y), int(q); return f"{y - 1}-Q4" if q == 1 else f"{y}-Q{q - 1}"
def _lag_year(k): return str(int(k) - 1)


REG["Tax Month-over-Month"] = lambda c: _compare(c, month, _lag_month, "Month"); REG["Tax Quarter-over-Quarter"] = lambda c: _compare(c, quarter, _lag_q, "Quarter")
REG["Tax Year-over-Year"] = lambda c: _compare(c, month, _lag_yoy_month, "Month vs same month last year")
REG["Tax Comparative Analysis"] = lambda c: _compare(c, year, _lag_year, "Year"); DOMAIN["Tax Comparative Analysis"] = DOMAIN["Tax Year-over-Year"] = "Analytics & AI"


@report("Tax Forecast", "Planning & Forecasting")
def _forecast(c):
    ser = _series(c, month, c.tax_type, date(c.end.year - 1, c.end.month, 1))
    cols = [("m", "Month", T), ("kind", "Actual / forecast", T), ("out", "Payable-type", M), ("inp", "Credit-type", M), ("net", "Net", M)]
    keys = list(ser)[-6:]
    rows = [{"m": k, "kind": "Actual", "out": f2(ser[k][0]), "inp": f2(ser[k][1]), "net": f2(ser[k][0] - ser[k][1])} for k in keys]
    if keys:
        n = len(keys); ao = sum(ser[k][0] for k in keys) / n; ai = sum(ser[k][1] for k in keys) / n
        y, m = map(int, keys[-1].split("-"))
        for i in range(1, 4):
            m += 1; y, m = (y + 1, 1) if m > 12 else (y, m)
            rows.append({"m": f"{y}-{m:02d}", "kind": f"Forecast (average of last {n} months)", "out": f2(ao), "inp": f2(ai), "net": f2(ao - ai)})
    return cols, rows


@report("Rate Sensitivity", "Planning & Forecasting")
def _rate_sens(c):
    rows_ = _cits(c, approved=False)
    cols = [("shift", "Rate change (points)", P), ("rate", "Rate %", P), ("tax", "Income tax", M), ("chg", "Change vs now", M)]
    if not rows_: return cols, []
    r = rows_[0]; rule = rule_index().get((r["income_tax_rule"] or "").upper())
    if not rule or rule.method != "percentage": return cols, []
    base, now = _d(r["assessable_profit"]), _d(r["income_tax"])
    return cols, [{"shift": s, "rate": float(rule.rate) + s, "tax": f2(base * (rule.rate + Decimal(s)) / 100), "chg": f2(base * (rule.rate + Decimal(s)) / 100 - now)} for s in (-5, -2.5, -1, 0, 1, 2.5, 5, 10)]


@report("Profit Sensitivity", "Planning & Forecasting")
def _profit_sens(c):
    rows_ = _cits(c, approved=False)
    cols = [("shift", "Change in adjusted profit %", P), ("adjusted", "Adjusted profit", M), ("assessable", "Assessable profit", M), ("tax", "Income tax", M), ("chg", "Change vs now", M)]
    if not rows_: return cols, []
    r = rows_[0]; rule = rule_index().get((r["income_tax_rule"] or "").upper())
    if not rule: return cols, []
    from velora_erp.tax import engine as eng
    out = []
    for s in (-30, -20, -10, 0, 10, 20, 30):
        adj = _d(r["adjusted_profit"]) * (100 + s) / 100
        ass = max(adj - _d(r["loss_relieved"]), ZERO) if adj > 0 else ZERO
        tax = eng.calculate(rule, ass).tax_amount if ass > 0 else ZERO
        out.append({"shift": s, "adjusted": f2(adj), "assessable": f2(ass), "tax": f2(tax), "chg": f2(tax - _d(r["income_tax"]))})
    return cols, out


for _n in ("Tax Sensitivity", "Tax Sensitivity Analysis", "Scenario Impact Analysis", "Tax Rate Change Impact"):
    REG[_n] = _rate_sens; DOMAIN[_n] = "Planning & Forecasting"
REG["Profit Sensitivity"] = _profit_sens; REG["Tax Sensitivity Analysis"] = _profit_sens


@report("Tax to Revenue Ratio", "Analytics & AI")
def _rev_ratio(c):
    from velora_erp.tax.cit import profit_and_loss
    rev = sum((x["net"] for x in profit_and_loss(c.start, c.end) if x["root_type"] == "Income"), ZERO)
    cols = [("what", "Measure", T), ("amount", "Amount", M), ("ratio", "% of revenue", P)]
    out = sum((r["tax"] for r in c.facts() if r["section"] == "Output"), ZERO)
    vat = sum((r["tax"] for r in c.facts() if r["section"] == "Output" and r["tax_type"] == "VAT"), ZERO)
    wht = sum((r["tax"] for r in c.facts() if r["tax_type"] == "WHT" and r["section"] == "Input"), ZERO)
    cit = sum((_d(r["income_tax_charge"]) + _d(r["levies"]) for r in _cits(c) if c.start <= as_date(r["period_end"]) <= c.end), ZERO)
    rows = [("Revenue (income accounts)", rev), ("Tax payable-type collected / withheld", out), ("of which VAT output", vat), ("WHT suffered (credits)", wht), ("Company income tax and levies charged", cit)]
    return cols, [{"what": a, "amount": f2(b), "ratio": round(float(b / rev * 100), 2) if rev else None} for a, b in rows]


REG["Tax Cash Rate"] = _rev_ratio; DOMAIN["Tax Cash Rate"] = "Analytics & AI"


@report("Tax Anomaly Register", "Analytics & AI")
def _anomaly(c):
    cols = [("date", "Date", DT), ("source_doctype", "Document type", T), ("source_name", "Document", T), ("party", "Party", T), ("tax_code", "Rule", T), ("net", "Taxable amount", M), ("tax", "Tax", M), ("severity", "Severity", T), ("why", "Why it stands out", T)]
    rows_all = c.facts(); by = defaultdict(list)
    for r in rows_all: by[r["tax_code"]].append(float(r["net"]))
    out = []
    for r in rows_all:
        why = []; sev = 0
        if r["rate"] and r["net"] and abs(float(r["tax"]) - float(r["net"]) * r["rate"] / 100) > max(0.05, abs(float(r["tax"])) * 0.01): why.append("tax does not equal rate x taxable amount"); sev = max(sev, 2)
        vals = by[r["tax_code"]]
        if len(vals) >= 8:
            mu, sd = statistics.mean(vals), statistics.pstdev(vals)
            if sd and abs(float(r["net"]) - mu) / sd > 3: why.append(f"amount is {abs(float(r['net']) - mu) / sd:.1f} standard deviations from the usual for {r['tax_code']}"); sev = max(sev, 2)
        if r["tax_type"] == "(no rule)": why.append("tax code has no approved rule"); sev = max(sev, 3)
        if r["created"] and (r["created"] - r["date"]).days > 60: why.append("posted more than 60 days after its date"); sev = max(sev, 1)
        if float(r["net"]) and float(r["net"]) % 1000 == 0 and abs(float(r["net"])) >= 100000: why.append("round amount"); sev = max(sev, 1)
        if why: out.append({"date": r["date"], "source_doctype": r["source_doctype"], "source_name": r["source_name"], "party": r["party"], "tax_code": r["tax_code"], "net": f2(r["net"]), "tax": f2(r["tax"]), "severity": ("Low", "Low", "Medium", "High")[sev], "why": "; ".join(why)})
    return cols, out


@report("Tax Anomaly Severity", "Analytics & AI")
def _anom_sev(c):
    g = defaultdict(lambda: [0, ZERO])
    for r in _anomaly(c)[1]: a = g[r["severity"]]; a[0] += 1; a[1] += _d(r["tax"])
    return [("s", "Severity", T), ("n", "Entries", I), ("t", "Tax involved", M)], [{"s": k, "n": v[0], "t": f2(v[1])} for k, v in sorted(g.items())]


REG["Tax Anomaly Exposure"] = _anom_sev; DOMAIN["Tax Anomaly Exposure"] = "Analytics & AI"; REG["Continuous Control Exceptions"] = _anomaly; DOMAIN["Continuous Control Exceptions"] = "Data Quality & Continuous Controls"
REG["Tax Exception Register"] = _anomaly; DOMAIN["Tax Exception Register"] = "Automation, Risk & Governance"
REG["Suspicious Tax Activity"] = lambda c: (_anomaly(c)[0], [r for r in _anomaly(c)[1] if r["severity"] in ("Medium", "High")]); DOMAIN["Suspicious Tax Activity"] = "Security & Audit Trail"
REG["Tax Fraud Indicators"] = REG["Suspicious Tax Activity"]; DOMAIN["Tax Fraud Indicators"] = "Security & Audit Trail"
REG["Continuous Control Exposure"] = _anom_sev; DOMAIN["Continuous Control Exposure"] = "Data Quality & Continuous Controls"


# ----------------------------------------------------------------------------------------------------- data quality and controls
def rule_rows():
    return L("Tax Rule", ["name", "rule_code", "rule_name", "tax_type", "jurisdiction", "category", "method", "rate", "effective_from", "effective_to", "tax_account", "approval_status", "version", "approved_by", "docstatus", "owner"], [["docstatus", "in", [0, 1]]], "rule_code asc", 5000)


@report("Tax Rule Quality", "Data Quality & Continuous Controls")
def _rule_q(c):
    cols = [("rule", "Rule", T), ("type", "Tax type", T), ("issue", "Issue", T), ("detail", "Detail", T)]
    rows, today = [], c.today
    by = defaultdict(list)
    for r in rule_rows():
        by[r["rule_code"]].append(r)
        code = r["rule_code"]
        if r["tax_type"] in ("VAT", "WHT", "Levy") and not r["tax_account"]: rows.append({"rule": code, "type": r["tax_type"], "issue": "No tax account", "detail": "Invoices and tax journals cannot post this tax"})
        if r["method"] == "Percentage" and float(r["rate"] or 0) == 0: rows.append({"rule": code, "type": r["tax_type"], "issue": "Zero rate", "detail": "Intended zero-rating, or a missing rate?"})
        if r["docstatus"] == 0: rows.append({"rule": code, "type": r["tax_type"], "issue": "Not yet approved", "detail": f"Approval {r['approval_status']}"})
        if r["effective_to"] and as_date(r["effective_to"]) < today: rows.append({"rule": code, "type": r["tax_type"], "issue": "Expired", "detail": f"Ended {as_date(r['effective_to'])}"})
        if r["tax_type"] in ("VAT", "WHT") and not r["jurisdiction"]: rows.append({"rule": code, "type": r["tax_type"], "issue": "No jurisdiction", "detail": ""})
    for code, rs in by.items():
        if len({r["jurisdiction"] for r in rs}) > 1: rows.append({"rule": code, "type": rs[0]["tax_type"], "issue": "Same code in several jurisdictions", "detail": ""})
    return cols, rows


for _n, _d_ in (("Tax Rate Quality", "Data Quality & Continuous Controls"), ("Expired Tax Configuration", "Data Quality & Continuous Controls")):
    REG[_n] = _rule_q; DOMAIN[_n] = _d_
REG["Expired Tax Configuration"] = lambda c: (_rule_q(c)[0], [r for r in _rule_q(c)[1] if r["issue"] == "Expired"])


@report("Account Mapping Quality", "Data Quality & Continuous Controls")
def _acc_q(c):
    cols = [("account", "Account", T), ("name", "Name", T), ("issue", "Issue", T), ("entries", "Entries", I)]
    sec = defaultdict(set); names = {}; codes = defaultdict(set)
    for r in load_facts(date(2000, 1, 1), c.end):
        sec[r["account"]].add(r["section"]); names[r["account"]] = r["account_name"]; codes[r["account"]].add(r["tax_type"])
    rows = [{"account": a, "name": names[a], "issue": "Used for both payable-type and credit-type tax", "entries": 0} for a, s in sec.items() if len(s) > 1]
    rows += [{"account": a, "name": names[a], "issue": "Used for more than one tax type: " + ", ".join(sorted(t)), "entries": 0} for a, t in codes.items() if len(t) > 1]
    accts = {r["tax_account"] for r in rule_rows() if r["tax_account"]}
    posted = set(sec)
    rows += [{"account": a, "name": "", "issue": "Rule account never used in the ledger", "entries": 0} for a in sorted(accts - posted)]
    return cols, rows


@report("Registration Quality", "Data Quality & Continuous Controls")
def _reg_q(c):
    cols = [("kind", "Party type", T), ("party", "Party", T), ("name", "Name", T), ("issue", "Issue", T)]
    rows = []
    for kind, fld, nm in (("Customer", "customer_name", "customer_name"), ("Supplier", "supplier_name", "supplier_name")):
        parties = {r["party"] for r in load_facts(date(2000, 1, 1), c.end) if r["party_type"] == kind}
        for p in L(kind, ["name", nm, "tax_registration_number"], None, None, 20000):
            if p["name"] in parties and not p["tax_registration_number"]: rows.append({"kind": kind, "party": p["name"], "name": p[nm], "issue": "Taxed transactions but no tax registration number"})
    return cols, rows


@report("Duplicate Tax Records", "Data Quality & Continuous Controls")
def _dups(c):
    cols = [("party", "Party", T), ("date", "Date", DT), ("tax", "Tax", M), ("net", "Taxable amount", M), ("docs", "Documents", T), ("n", "Count", I)]
    g = defaultdict(list)
    for r in c.facts(): g[(r["party"], r["date"], float(r["tax"]), float(r["net"]), r["tax_code"])].append(r["source_name"])
    return cols, [{"party": k[0], "date": k[1], "tax": f2(k[2]), "net": f2(k[3]), "docs": ", ".join(sorted(set(v))), "n": len(v)} for k, v in g.items() if len(v) > 1 and k[0] and len(set(v)) > 1]


def checks(c):
    """Pass/fail counts used by the scorecards: (area, check, failed, total)."""
    fx = c.facts(); n = len(fx)
    mism = sum(1 for r in fx if r["rate"] and r["net"] and abs(float(r["tax"]) - float(r["net"]) * r["rate"] / 100) > max(0.05, abs(float(r["tax"])) * 0.01))
    norule = sum(1 for r in fx if r["tax_type"] == "(no rule)")
    nojur = sum(1 for r in fx if not r["jurisdiction"])
    rq = _rule_q(c)[1]; nrules = len(rule_rows()) or 1
    reg = len(_reg_q(c)[1]); dup = len(_dups(c)[1]); am = len(_acc_q(c)[1])
    ob = _obl(c)
    return [("Ledger", "Tax equals rate x taxable amount", mism, n), ("Ledger", "Tax code has an approved rule", norule, n), ("Ledger", "Tax line has a jurisdiction", nojur, n), ("Ledger", "No duplicate tax records", dup, max(n, 1)),
            ("Rules", "Rules complete and current", len(rq), nrules), ("Accounts", "Tax accounts mapped consistently", am, max(len(tax_accounts()), 1)), ("Parties", "Taxed parties have a registration number", reg, max(len({r['party'] for r in fx if r['party']}), 1)),
            ("Filing", "Obligations not overdue", sum(1 for o in ob if o["state"] == "Overdue"), max(len(ob), 1))]


@report("Tax Data Quality Scorecard", "Data Quality & Continuous Controls")
def _dq(c):
    cols = [("area", "Area", T), ("check", "Check", T), ("failed", "Failed", I), ("total", "Checked", I), ("score", "Score %", P)]
    rows = [{"area": a, "check": k, "failed": f, "total": t, "score": round(100 * (1 - min(f, t) / t), 1) if t else 100.0} for a, k, f, t in checks(c)]
    rows.append({"area": "Overall", "check": "Average of the checks above", "failed": sum(r["failed"] for r in rows), "total": sum(r["total"] for r in rows), "score": round(sum(r["score"] for r in rows) / len(rows), 1)})
    return cols, rows


for _n, _d_ in (("Data Quality by Tax Type", "Data Quality & Continuous Controls"), ("Data Quality by Jurisdiction", "Data Quality & Continuous Controls"), ("Tax Control Scorecard", "Group & Executive Management"), ("Tax Governance Scorecard", "Automation, Risk & Governance"),
                ("Continuous Control Register", "Data Quality & Continuous Controls"), ("Tax Control Register", "Automation, Risk & Governance"), ("Control Failures", "Automation, Risk & Governance")):
    REG[_n] = _dq; DOMAIN[_n] = _d_
REG["Control Failures"] = lambda c: (_dq(c)[0], [r for r in _dq(c)[1] if r["failed"] and r["area"] != "Overall"])


@report("Data Quality Trend", "Data Quality & Continuous Controls")
def _dq_trend(c):
    cols = [("m", "Month", T), ("n", "Tax entries", I), ("bad", "With a problem", I), ("score", "Clean %", P)]
    bad = {(r["source_name"], r["tax_code"], str(r["date"])) for r in _anomaly(c)[1]}
    g = defaultdict(lambda: [0, 0])
    for r in c.facts():
        a = g[month(r["date"])]; a[0] += 1; a[1] += (r["source_name"], r["tax_code"], str(r["date"])) in bad
    return cols, [{"m": k, "n": v[0], "bad": v[1], "score": round(100 * (1 - v[1] / v[0]), 1)} for k, v in sorted(g.items())]


# ----------------------------------------------------------------------------------------------------- change and approval history
@report("Tax Rule Change Register", "Security & Audit Trail")
def _rule_hist(c):
    cols = [("code", "Rule", T), ("version", "Version", I), ("type", "Tax type", T), ("method", "Method", T), ("rate", "Rate %", P), ("from", "Effective from", DT), ("to", "Effective to", DT), ("status", "Approval", T), ("by", "Approved by", T), ("created_by", "Created by", T)]
    return cols, [{"code": r["rule_code"], "version": r["version"], "type": r["tax_type"], "method": r["method"], "rate": r["rate"], "from": as_date(r["effective_from"]), "to": as_date(r["effective_to"]), "status": r["approval_status"], "by": r["approved_by"], "created_by": r["owner"]} for r in rule_rows()]


for _n in ("Tax Rate Change Register", "Tax Configuration Change Register", "Regulatory Change Register", "Tax Policy Register"):
    REG[_n] = _rule_hist; DOMAIN[_n] = "Security & Audit Trail" if _n.startswith("Tax ") and "Policy" not in _n else "Automation, Risk & Governance"


def _approvals(c):
    rows = []
    for dt, dcol in (("Tax Rule", "effective_from"), ("Tax Return", "period_end"), ("Tax Journal", "posting_date"), ("Income Tax Computation", "period_end")):
        for r in L(dt, ["name", dcol, "approval_status", "approved_by", "owner"], [["docstatus", "in", [0, 1]]], None, 3000):
            rows.append({"doc": dt, "name": r["name"], "date": as_date(r[dcol]), "status": r["approval_status"], "approved_by": r["approved_by"] or "", "created_by": r["owner"] or ""})
    return rows


@report("Tax Approval History", "Security & Audit Trail")
def _appr(c): return [("doc", "Document type", T), ("name", "Document", T), ("date", "Date", DT), ("status", "Approval", T), ("approved_by", "Approved by", T), ("created_by", "Created by", T)], _approvals(c)


@report("Segregation of Duties Conflicts", "Security & Audit Trail")
def _sod(c): return _appr(c)[0], [r for r in _approvals(c) if r["approved_by"] and r["approved_by"] == r["created_by"]]


for _n in ("SoD Exceptions", "Control Execution Register"):
    REG[_n] = _sod if _n.startswith("SoD") else _appr; DOMAIN[_n] = "Security & Audit Trail" if _n.startswith("SoD") else "Automation, Risk & Governance"


# ----------------------------------------------------------------------------------------------------- executive summary
@report("Executive Tax Report", "Group & Executive Management")
def _exec(c):
    from velora_erp.tax import adviser, deadlines
    cols = [("area", "Area", T), ("measure", "Measure", T), ("value", "Value", T), ("note", "Note", T)]
    fx = c.facts(); fmt = lambda v: f"{float(v):,.2f}"
    s = lambda pred: sum((r["tax"] for r in fx if pred(r)), ZERO)
    rows = [("Position", "VAT output", fmt(s(lambda r: VAT(r) and r["section"] == "Output")), ""), ("Position", "VAT input", fmt(s(lambda r: VAT(r) and r["section"] == "Input")), ""),
            ("Position", "VAT net payable (negative = refundable)", fmt(s(lambda r: VAT(r) and r["section"] == "Output") - s(lambda r: VAT(r) and r["section"] == "Input")), ""),
            ("Position", "WHT withheld by us (payable)", fmt(s(lambda r: WHT(r) and r["section"] == "Output")), ""), ("Position", "WHT credits suffered", fmt(s(lambda r: WHT(r) and r["section"] == "Input")), "")]
    cits = _cits(c)
    if cits: rows.append(("Income tax", f"Latest approved computation {cits[0]['name']}", fmt(_d(cits[0]["income_tax_charge"]) + _d(cits[0]["levies"])), f"net payable {fmt(cits[0]['net_payable'])} after credits"))
    ob = _obl(c); over = [o for o in ob if o["state"] == "Overdue"]
    rows.append(("Compliance", "Open obligations", str(sum(1 for o in ob if o["state"] != "Closed")), f"{len(over)} overdue"))
    rows.append(("Compliance", "Estimated penalty and interest exposure", fmt(sum((deadlines.exposure(o, c.today)["penalty"] + deadlines.exposure(o, c.today)["interest"] for o in over), ZERO)), "from the rates in Tax Settings"))
    sc = _dq(c)[1][-1]; rows.append(("Quality", "Tax data quality score", f"{sc['score']}%", f"{sc['failed']} failed of {sc['total']} checks"))
    for f in adviser.findings(c.today)[:8]: rows.append(("Adviser - " + f["severity"], f["title"], "", f["detail"]))
    return cols, [{"area": a, "measure": m, "value": v, "note": n} for a, m, v, n in rows]


REG["Tax Executive Summary"] = _exec; DOMAIN["Tax Executive Summary"] = "Analytics & AI"; REG["Tax Security Dashboard"] = _exec; DOMAIN["Tax Security Dashboard"] = "Security & Audit Trail"


# ----------------------------------------------------------------------------------------------------- pruning
# Names that were only another label for a report already in the library, or promised something the report does not deliver
# (for example "Penalty Computation" was the overdue list). They are removed so every name in the library is a distinct, useful report.
REMOVED = (
    'At-Risk Work',
    'Authority Statement Reconciliation',
    'Continuous Control Exceptions',
    'Continuous Control Exposure',
    'Continuous Control Register',
    'Control Execution Register',
    'DTA Recognition Analysis',
    'Data Quality by Jurisdiction',
    'Data Quality by Tax Type',
    'Deferred Tax Provision',
    'Filing Reference Register',
    'Group Compliance Summary',
    'Group Effective Tax Rate',
    'Group Interest Exposure',
    'Group Outstanding Liability',
    'Group Penalty Exposure',
    'Group Tax Cash Flow',
    'Group Tax Credits',
    'Group Tax Liability',
    'Group Tax Payments',
    'Interest Computation',
    'Invalid Tax Data',
    'Outstanding Tax Liability',
    'Overdue Tax Payments',
    'Penalty Computation',
    'Regulatory Change Register',
    'Resubmission Register',
    'Scenario Impact Analysis',
    'SoD Exceptions',
    'Tax Anomaly Exposure',
    'Tax Base Register',
    'Tax Cash Rate',
    'Tax Configuration Change Register',
    'Tax Control Register',
    'Tax Control Scorecard',
    'Tax Credit Register',
    'Tax Credit Utilization',
    'Tax Effective Rate',
    'Tax Exception Register',
    'Tax Executive Summary',
    'Tax Fraud Indicators',
    'Tax Governance Scorecard',
    'Tax Liability Forecast',
    'Tax Payment Forecast',
    'Tax Policy Register',
    'Tax Rate Change Impact',
    'Tax Rate Change Register',
    'Tax Rate Quality',
    'Tax Security Dashboard',
    'Tax Sensitivity',
    'Tax Sensitivity Analysis',
    'Tax Settlement Register',
    'Tax to Profit Ratio',
    'Tax vs Profit Analysis',
    'Unutilized Tax Credits',
    'Upcoming Tax Payments',
    'VAT Return Detail',
    'WHT Credit Register',
    'WHT Return Detail',
    'WHT Unutilized Credits',
)
for _n in REMOVED:
    REG.pop(_n, None); DOMAIN.pop(_n, None)


# ----------------------------------------------------------------------------------------------------- running a report
def run(name, start, end, tax_type=None, jurisdiction=None, party=None):
    fn = REG.get(name)
    if fn is None:
        from velora import throw
        throw(f"'{name}' is not a tax report that this system can run.")
    cols, rows = fn(Ctx(start, end, tax_type, jurisdiction, party))
    return cols, rows


def available() -> list[str]:
    return sorted(n for n, f in REG.items() if f is not None)
