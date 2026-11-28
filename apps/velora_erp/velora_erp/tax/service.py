"""Tax Management inside VeloraERP: rule resolution, invoice standardisation, the tax ledger read from the GL, returns and obligations.

Design choices (so the books stay single-source):
* The GL already carries every posted tax line (tax code, rate, taxable amount, tax amount). The *tax ledger* is read from it, not copied.
  Cancelled or reversed documents net out because their reversing entries are in the same table.
* Tax Rules are effective-dated and approved through the GUI workflow like payroll tax rules; only approved, submitted rules are ever used.
* Payroll tax is untouched. This module neither reads nor writes Payroll Tax Rule/Jurisdiction.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.tax import engine as eng

ZERO = Decimal("0")
OPEN_STATES = ("Open", "In Preparation", "Under Review", "Rejected")
RETURN_FLOW = {"Draft": {"Calculated"}, "Calculated": {"Draft", "Filed"}, "Filed": {"Accepted", "Rejected"}, "Rejected": set(), "Accepted": set()}


def _fp(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _n(v) -> str:
    """A number as text that does not depend on how it was stored (7.5, 7.500000 and Decimal('7.5') are the same)."""
    d = _d(v).normalize()
    return "0" if d == 0 else format(d, "f")


def _date(v):
    return v if isinstance(v, date) and not isinstance(v, datetime) else date.fromisoformat(str(v)[:10])


# ------------------------------------------------------------------ rules

def engine_rule(doc) -> eng.Rule:
    tiers = []
    for t in sorted(doc.get("tiers") or [], key=lambda r: _d(r.lower_limit)):
        tiers.append((_d(t.lower_limit), None if t.upper_limit in (None, "") else _d(t.upper_limit), _d(t.rate)))
    return eng.Rule(code=doc.rule_code, name=doc.rule_name or "", tax_type=doc.tax_type, jurisdiction=doc.jurisdiction, method=(doc.method or "Percentage").lower(),
                    rate=_d(doc.rate), fixed_amount=_d(doc.fixed_amount), category=doc.category or None, effective_from=_date(doc.effective_from),
                    effective_to=_date(doc.effective_to) if doc.effective_to else None, inclusive=bool(doc.inclusive),
                    recoverability_percent=_d(doc.recoverability_percent if doc.recoverability_percent is not None else 100),
                    precision=int(doc.rounding_precision if doc.rounding_precision is not None else 2), tiers=tuple(tiers))


class TaxRule(Document):
    def validate(self):
        validate_approval_transition(self)
        self.rule_code = (self.rule_code or "").strip().upper()
        if not self.rule_code:
            throw("Tax code is required.")
        try:
            eng.validate_rule(engine_rule(self))
        except eng.TaxConfigError as exc:
            throw(str(exc))
        if (self.method or "Percentage") != "Tiered" and self.get("tiers"):
            throw("Bands apply only to a Tiered rule. Remove them or change the method.")
        if self.tax_account:
            acc = get_list("Account", filters=[["name", "=", self.tax_account]], fields=["root_type", "disabled"], limit=1, ignore_permissions=True)
            if not acc or acc[0].get("disabled") or acc[0]["root_type"] not in ("Liability", "Asset"):
                throw("The tax account must be an enabled liability (output tax) or asset (input tax) account.")
        end = str(self.effective_to or "9999-12-31")
        for o in get_list("Tax Rule", filters=[["rule_code", "=", self.rule_code], ["jurisdiction", "=", self.jurisdiction], ["docstatus", "!=", 2]],
                          fields=["name", "category", "effective_from", "effective_to"], limit=1000, ignore_permissions=True):
            if o["name"] == self.name or (o.get("category") or None) != (self.category or None):
                continue
            if str(self.effective_from) <= str(o.get("effective_to") or "9999-12-31") and end >= str(o["effective_from"]):
                throw(f"Effective dates overlap {o['name']} for the same tax code, jurisdiction and category.")
        fp = _fp({"c": self.rule_code, "t": self.tax_type, "j": self.jurisdiction, "cat": self.category, "m": self.method, "r": _n(self.rate), "f": _n(self.fixed_amount),
                  "inc": bool(self.inclusive), "rec": _n(self.recoverability_percent), "p": int(self.rounding_precision or 0), "from": str(self.effective_from), "to": str(self.effective_to or ""),
                  "acct": self.tax_account, "tiers": [(_n(t.lower_limit), "" if t.upper_limit in (None, "") else _n(t.upper_limit), _n(t.rate)) for t in sorted(self.get("tiers") or [], key=lambda x: _d(x.lower_limit))]})
        old = getattr(self, "_old", None) or {}
        if old.get("approval_status") == "Approved" and self.approval_status == "Approved" and old.get("approval_hash") not in (None, fp):
            throw("An approved Tax Rule cannot be changed. Cancel it and amend it so the change is approved again.")
        self.approval_hash = fp if self.approval_status == "Approved" else None

    def before_submit(self):
        ensure_approved(self, required=True)
        if self.approval_status != "Approved":
            throw("A Tax Rule must be approved before it can be submitted.")


def load_rules(on: date | None = None, tax_type: str | None = None) -> list[eng.Rule]:
    """Approved, submitted rules (optionally only those in force on a date)."""
    filters = [["docstatus", "=", 1], ["approval_status", "=", "Approved"]]
    if tax_type:
        filters.append(["tax_type", "=", tax_type])
    out = []
    for r in get_list("Tax Rule", filters=filters, fields=["name"], limit=100000, ignore_permissions=True):
        rule = engine_rule(get_doc("Tax Rule", r["name"], ignore_permissions=True))
        if on is None or rule.applies_on(on):
            out.append(rule)
    return out


def rules_by_code(on: date) -> dict:
    """{code: [Rule, ...]} for rules in force on a date, one query pass (used by invoices and returns)."""
    out: dict = {}
    for r in load_rules(on):
        out.setdefault(r.code, []).append(r)
    return out


class TaxSettings(Document):
    def validate(self):
        if int(self.filing_reminder_days or 0) < 0:
            throw("Reminder days cannot be negative.")


def settings() -> dict:
    rows = get_list("Tax Settings", fields=["require_registered_codes", "default_jurisdiction", "filing_reminder_days", "require_wht_certificate", "default_income_tax_rule",
                                            "default_minimum_tax_rule", "default_levy_rules", "wht_remittance_day", "vat_filing_day", "late_penalty_flat", "late_penalty_monthly_percent",
                                            "late_interest_annual_percent"], limit=1, ignore_permissions=True)
    return rows[0] if rows else {"require_registered_codes": 0, "default_jurisdiction": None, "filing_reminder_days": 7, "require_wht_certificate": 0,
                                 "default_income_tax_rule": None, "default_minimum_tax_rule": None, "default_levy_rules": None, "wht_remittance_day": None, "vat_filing_day": None,
                                 "late_penalty_flat": 0, "late_penalty_monthly_percent": 0, "late_interest_annual_percent": 0}


# ------------------------------------------------------------------ invoice standardisation

def standardise_invoice_line(doc, line, index: int, cache: dict) -> None:
    """Make an invoice line's tax follow the approved Tax Rule that its Tax Code names.

    A code that names a rule sets the rate (and the tax account when empty). With *Invoice tax codes must be approved Tax Rules* on, a taxed line
    must name one. Only percentage, tax-exclusive rules can sit on invoice lines; fixed and tiered rules are used by returns and the calculator.
    """
    on = _date(getattr(doc, "invoice_date", None) or getattr(doc, "posting_date", None) or date.today())
    st = cache.setdefault("settings", settings())
    code = (getattr(line, "tax_code", None) or "").strip().upper()
    taxed = _d(getattr(line, "tax_rate", 0)) > 0 or _d(getattr(line, "tax_amount", 0)) > 0 or bool(getattr(line, "tax_account", None))
    if not code:
        if st.get("require_registered_codes") and taxed:
            throw(f"Line {index}: a taxed line needs a Tax Code that names an approved Tax Rule.")
        return
    by_code = cache.setdefault(("rules", on), rules_by_code(on))
    matches = by_code.get(code, [])
    if len(matches) > 1 and st.get("default_jurisdiction"):
        matches = [m for m in matches if m.jurisdiction == st["default_jurisdiction"]] or matches
    if len(matches) > 1:
        throw(f"Line {index}: Tax Code {code} matches rules in more than one jurisdiction. Set a default jurisdiction in Tax Settings.")
    if not matches:
        if st.get("require_registered_codes"):
            throw(f"Line {index}: Tax Code {code} is not an approved Tax Rule in force on {on}.")
        return
    rule = matches[0]
    if rule.method != "percentage" or rule.inclusive:
        throw(f"Line {index}: Tax Code {code} is a {'tax-inclusive ' if rule.inclusive else rule.method + ' '}rule. Only percentage, tax-exclusive codes can be used on invoice lines.")
    line.tax_rate = float(rule.rate)
    if _d(getattr(line, "tax_amount", 0)) == 0 and _d(getattr(line, "amount", 0)) > 0:
        line.tax_amount = eng.quantize(_d(line.amount) * rule.rate / eng.HUNDRED, rule.precision)      # lines priced by quantity x rate are recomputed by the invoice
    if not getattr(line, "tax_account", None):
        acct = get_list("Tax Rule", filters=[["rule_code", "=", code], ["docstatus", "=", 1], ["approval_status", "=", "Approved"]], fields=["tax_account", "effective_from", "effective_to"], limit=50, ignore_permissions=True)
        acct = [a for a in acct if str(a["effective_from"]) <= str(on) and str(a.get("effective_to") or "9999-12-31") >= str(on) and a.get("tax_account")]
        if acct:
            line.tax_account = acct[0]["tax_account"]


# ------------------------------------------------------------------ calculator

def calculate(tax_type, jurisdiction, amount, on=None, category=None, tax_inclusive=None, gross_for_withholding=False) -> dict:
    on = _date(on or date.today())
    try:
        rule = eng.select_rule(load_rules(on, tax_type), tax_type, jurisdiction, on, category)
        res = eng.calculate(rule, amount, tax_inclusive=tax_inclusive)
    except (LookupError, eng.TaxConfigError) as exc:
        throw(str(exc))
    out = {"rule": res.rule_code, "tax_type": res.tax_type, "jurisdiction": res.jurisdiction, "taxable_amount": str(res.taxable_amount), "tax_amount": str(res.tax_amount),
           "recoverable_amount": str(res.recoverable_amount), "non_recoverable_amount": str(res.non_recoverable_amount), "rate": str(res.rate), "trace": list(res.trace)}
    if gross_for_withholding or tax_type == "WHT":
        w = eng.withhold(res, amount)
        out.update({"withheld": str(w["withheld"]), "net_payable": str(w["net_payable"])})
    return out


# ------------------------------------------------------------------ the tax ledger (read from the GL)

def ledger_rows(start, end, tax_code: str | None = None) -> list[dict]:
    """Posted tax lines in the base currency, one row per GL record, signed so that output tax and input tax are both positive in their own direction."""
    r, a = get_table("Account Ledger Record"), get_table("Account")
    q = (select(r.c.name, r.c.posting_date, r.c.source_doctype, r.c.source_name, r.c.tax_code, r.c.tax_rate, r.c.base_debit, r.c.base_credit, r.c.base_taxable_amount, r.c.taxable_amount,
                r.c.tax_jurisdiction, r.c.party, a.c.root_type)
         .join(a, a.c.name == r.c.account)
         .where(r.c.tax_code.is_not(None), r.c.tax_code != "", r.c.posting_date >= start, r.c.posting_date <= end))
    if tax_code:
        q = q.where(r.c.tax_code == tax_code.strip())
    with db.transaction() as c:
        rows = c.execute(q.order_by(r.c.posting_date, r.c.name)).mappings().all()
    out = []
    for x in rows:
        debit, credit = _d(x["base_debit"]), _d(x["base_credit"])
        if x["root_type"] == "Liability":
            section, tax = "Output tax", credit - debit
        elif x["root_type"] == "Asset":
            section, tax = "Input tax", debit - credit
        else:
            continue
        net = _d(x["base_taxable_amount"] or x["taxable_amount"])
        out.append({"record": x["name"], "date": x["posting_date"], "source_doctype": x["source_doctype"], "source_name": x["source_name"], "party": x["party"],
                    "section": section, "tax_code": (x["tax_code"] or "").strip(), "tax_rate": float(_d(x["tax_rate"])),
                    "net": net if tax >= 0 else -net, "tax": tax, "jurisdiction": x["tax_jurisdiction"]})
    return out


def build_return_lines(tax_type, jurisdiction, start, end) -> tuple[list[dict], list[str]]:
    """Aggregate the ledger for the codes that belong to this tax type and jurisdiction. Codes with no approved rule are listed as warnings."""
    rules = {}
    for r in load_rules(None):
        rules.setdefault(r.code, []).append(r)           # all approved rules, any date: a code's tax type and jurisdiction do not change over time
    agg: dict = {}
    unknown = set()
    for row in ledger_rows(start, end):
        cands = [x for x in rules.get((row["tax_code"] or "").upper(), []) if x.applies_on(_date(row["date"]))] or rules.get((row["tax_code"] or "").upper(), [])
        if not cands:
            unknown.add(row["tax_code"]); continue
        rule = cands[0]
        if rule.tax_type != tax_type or rule.jurisdiction != jurisdiction:
            continue
        key = (row["section"], row["tax_code"], row["tax_rate"])
        a = agg.setdefault(key, {"section": row["section"], "tax_code": row["tax_code"], "tax_rate": row["tax_rate"], "net_amount": ZERO, "tax_amount": ZERO, "recoverable_amount": ZERO, "non_recoverable_amount": ZERO})
        a["net_amount"] += row["net"]; a["tax_amount"] += row["tax"]
        if row["section"] == "Input tax":
            rec = eng.quantize(row["tax"] * rule.recoverability_percent / eng.HUNDRED, rule.precision)
            a["recoverable_amount"] += rec; a["non_recoverable_amount"] += row["tax"] - rec
        else:
            a["recoverable_amount"] += row["tax"]
    warnings = []
    if unknown:
        warnings.append("Posted with tax codes that match no approved Tax Rule (not in any return): " + ", ".join(sorted(c or "(blank)" for c in unknown)))
    return [dict(v, net_amount=v["net_amount"], tax_amount=v["tax_amount"]) for k, v in sorted(agg.items())], warnings


class TaxReturn(Document):
    def validate(self):
        validate_approval_transition(self)
        if self.period_end and self.period_start and str(self.period_end) < str(self.period_start):
            throw("Period end cannot be before period start.")
        old = getattr(self, "_old", None) or {}
        if old and old.get("return_status") != self.return_status and self.docstatus == 0 and self.return_status not in ("Draft", "Calculated"):
            throw("The return status changes through Calculate, File and Record outcome.")
        if self.docstatus == 0 and self.return_status == "Calculated":
            self._totals()

    def _totals(self):
        out = sum((_d(l.tax_amount) for l in self.lines if l.section == "Output tax"), ZERO)
        rec = sum((_d(l.recoverable_amount) for l in self.lines if l.section == "Input tax"), ZERO)
        non = sum((_d(l.non_recoverable_amount) for l in self.lines if l.section == "Input tax"), ZERO)
        self.output_tax, self.input_tax, self.non_recoverable_tax, self.net_payable = out, rec, non, out - rec

    def _fresh_hash(self):
        lines, _ = build_return_lines(self.tax_type, self.jurisdiction, self.period_start, self.period_end)
        return _fp([(l["section"], l["tax_code"], str(l["tax_amount"]), str(l["net_amount"])) for l in lines])

    def before_submit(self):
        ensure_approved(self, required=True)
        if self.return_status != "Calculated" or not self.source_hash:
            throw("Calculate the return before submitting it.")
        if self._fresh_hash() != self.source_hash:
            throw("The ledger has changed since this return was calculated. Calculate it again, then resubmit for approval.")


def calculate_return(name: str) -> dict:
    doc = get_doc("Tax Return", name)
    if doc.docstatus != 0:
        throw("Only a draft return can be calculated. Cancel and amend a submitted one.")
    lines, warnings = build_return_lines(doc.tax_type, doc.jurisdiction, doc.period_start, doc.period_end)
    doc.set("lines", [{**l, "net_amount": l["net_amount"], "tax_amount": l["tax_amount"]} for l in lines])
    doc.return_status = "Calculated"
    doc.calculated_on = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    doc.source_hash = _fp([(l["section"], l["tax_code"], str(l["tax_amount"]), str(l["net_amount"])) for l in lines])
    doc.save()
    return {"name": doc.name, "output_tax": str(doc.output_tax), "input_tax": str(doc.input_tax), "non_recoverable_tax": str(doc.non_recoverable_tax), "net_payable": str(doc.net_payable), "lines": len(lines), "warnings": warnings}


def file_return(name: str, filing_reference: str) -> dict:
    doc = get_doc("Tax Return", name)
    if doc.docstatus != 1 or doc.approval_status != "Approved" or doc.return_status != "Calculated":
        throw("Only an approved, submitted and calculated return can be filed.")
    if not (filing_reference or "").strip():
        throw("A filing reference is required.")
    db_update(doc, return_status="Filed", filing_reference=filing_reference.strip())
    _sync_obligation(doc, "Filed")
    return {"name": doc.name, "return_status": "Filed"}


def record_outcome(name: str, accepted: bool, acknowledgement: str = "") -> dict:
    doc = get_doc("Tax Return", name)
    if doc.return_status != "Filed" or doc.docstatus != 1:
        throw("Only a filed return can be accepted or rejected.")
    status = "Accepted" if accepted else "Rejected"
    db_update(doc, return_status=status, acknowledgement=(acknowledgement or "").strip() or None)
    _sync_obligation(doc, status)
    return {"name": doc.name, "return_status": status}


def _sync_obligation(ret, status):
    if ret.obligation:
        ob = get_doc("Tax Obligation", ret.obligation, ignore_permissions=True)
        db_update(ob, status=status, tax_return=ret.name, filing_reference=ret.filing_reference, overdue=0)


class TaxObligation(Document):
    def validate(self):
        if str(self.period_end) < str(self.period_start):
            throw("Period end cannot be before period start.")
        if str(self.due_date) < str(self.period_end):
            throw("The due date cannot be before the period ends.")
        self.overdue = 1 if self.status in OPEN_STATES and str(self.due_date) < date.today().isoformat() else 0


def refresh_obligations() -> int:
    """Mark overdue obligations (run daily; also safe to run by hand)."""
    n = 0
    today = date.today().isoformat()
    for o in get_list("Tax Obligation", filters=[["status", "in", list(OPEN_STATES)]], fields=["name", "due_date", "overdue"], limit=100000, ignore_permissions=True):
        flag = 1 if str(o["due_date"]) < today else 0
        if flag != int(o.get("overdue") or 0):
            db_update(get_doc("Tax Obligation", o["name"], ignore_permissions=True), overdue=flag); n += 1
    from velora_erp.tax import deadlines
    n += deadlines.ensure_obligations()
    deadlines.remind()
    return n


# ------------------------------------------------------------------ report catalogue

_CAT = {}


def catalogue() -> list[dict]:
    """The catalogued tax reports that can be run, de-duplicated and cleaned (the 460 specifications are kept in data/ but only those with a data source are listed): no CSV, no company filter (this ERP has no company field), a stable id and an honest status."""
    if "c" not in _CAT:
        import pathlib
        raw = json.loads((pathlib.Path(__file__).parent / "data" / "tax_report_catalogue.json").read_text(encoding="utf-8"))["reports"]
        from velora_erp.tax import library
        have = set(library.available())
        seen, out = {}, []
        for r in raw:
            key = (r["domain"], r["report_name"])
            seen[key] = seen.get(key, 0) + 1
            slug = "".join(ch if ch.isalnum() else "-" for ch in f"{r['domain']}-{r['report_name']}".lower()).strip("-")
            slug = "-".join(p for p in slug.split("-") if p) + (f"-{seen[key]}" if seen[key] > 1 else "")
            out.append({"id": slug, "domain": r["domain"], "report_name": r["report_name"] + (f" ({seen[key]})" if seen[key] > 1 else ""),
                        "filters": [f for f in r.get("filters", []) if f != "company"],
                        "features": [f for f in r.get("features", []) if f != "csv_export"],
                        "status": IMPLEMENTED.get(key) or ("Tax Report Library" if r["report_name"] in have else "specification")})
        _CAT["c"] = [r for r in out if r["status"] != "specification"]   # only reports that can be run are listed
    return _CAT["c"]


# report name (domain, name) -> the executable report that covers it
IMPLEMENTED = {("VAT & GST", "VAT Return Summary"): "Tax Return Summary", ("VAT & GST", "VAT Transaction Register"): "Tax Ledger",
               ("VAT & GST", "Output VAT Register"): "Tax Ledger", ("VAT & GST", "Input VAT Register"): "Tax Ledger",
               ("Compliance & Filing", "Tax Compliance Calendar"): "Tax Obligation Calendar",
               **{("WHT", n): "WHT Register" for n in ("WHT Transaction Register", "WHT Withheld from Suppliers", "WHT Suffered on Receipts", "WHT Certificate Issued Register",
                                                      "WHT Certificate Received Register", "WHT Payable Register", "WHT Credit Register")},
               ("WHT", "WHT by Supplier"): "WHT Position by Party", ("WHT", "WHT Credit Utilization"): "WHT All Sources", ("WHT", "WHT Unutilized Credits"): "WHT All Sources", ("WHT", "WHT by Customer"): "WHT Position by Party", ("WHT", "WHT Return Summary"): "Tax Return Summary",
               **{("CIT & Tax Computation", n): "Tax Treatment of Accounts" for n in ("Disallowable Expense Analysis", "Partial Deductibility Analysis", "Allowable Expense Analysis", "Tax Adjustment Register")},
               **{("CIT & Tax Computation", n): "Income Tax Computation Summary" for n in ("CIT Computation", "Taxable Income Summary", "Profit to Taxable Profit Bridge", "Loss Carryforward Register",
                                                                                      "Loss Utilization", "CIT Rate and Levy Analysis", "Minimum Tax Analysis", "Tax Credit Register")}}
