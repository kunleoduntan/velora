"""Company income tax computation.

Profit comes from the general ledger (income less expense accounts, base currency). Each account carries its own tax treatment
(Account > Tax treatment), so the add-backs are found by the system and the same answer is reached every year:

    profit per books
  + expenses of accounts marked Not tax allowed / Partly allowable / Capital   (add backs)
  - income of accounts marked Exempt income, and manual deductions
  - capital allowances (entered as lines - there is no asset-by-asset allowance engine here)
  = adjusted profit  ->  less losses brought forward  ->  assessable profit
  x the approved Income Tax rule (flat or tiered)  [higher of that and minimum tax on turnover]
  + levies on assessable profit (approved Levy rules)
  - withholding tax credits suffered in the period
  = net tax payable

Rates are never built in: they are approved Tax Rules.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.tax import engine as eng
from velora_erp.tax.service import _d, _date, _fp, ledger_rows, load_rules

ZERO = Decimal("0")
AUTO = "Automatic"


def profit_and_loss(start, end) -> list[dict]:
    """Income and expense balances by account for a period, with each account's tax treatment."""
    r, a = get_table("Account Ledger Record"), get_table("Account")
    q = (select(r.c.account, a.c.account_name, a.c.root_type, a.c.tax_treatment, a.c.disallowed_percent, r.c.base_debit, r.c.base_credit)
         .join(a, a.c.name == r.c.account).where(a.c.root_type.in_(["Income", "Expense"]), r.c.posting_date >= start, r.c.posting_date <= end))
    agg: dict = {}
    with db.transaction() as c:
        for x in c.execute(q).mappings():
            row = agg.setdefault(x["account"], {"account": x["account"], "name": x["account_name"], "root_type": x["root_type"], "treatment": x["tax_treatment"] or "Allowable",
                                                "percent": _d(x["disallowed_percent"]), "net": ZERO})
            dr, cr = _d(x["base_debit"]), _d(x["base_credit"])
            row["net"] += (cr - dr) if x["root_type"] == "Income" else (dr - cr)
    return sorted(agg.values(), key=lambda v: (v["root_type"], v["account"]))


def _rule(code, tax_type, on, label):
    if not code:
        return None
    for r in load_rules(on, tax_type):
        if r.code == code.strip().upper():
            return r
    throw(f"No approved {label} rule {code} is in force on {on}.")


def facts(start, end) -> dict:
    pl = profit_and_loss(start, end)
    turnover = sum((x["net"] for x in pl if x["root_type"] == "Income"), ZERO)
    expenses = sum((x["net"] for x in pl if x["root_type"] == "Expense"), ZERO)
    lines = []
    for x in pl:
        if x["net"] == 0:
            continue
        if x["root_type"] == "Expense" and x["treatment"] in ("Not tax allowed", "Partly allowable", "Capital (use capital allowance)"):
            pct = x["percent"] if x["treatment"] == "Partly allowable" else Decimal("100")
            amt = eng.quantize(x["net"] * pct / eng.HUNDRED, 2)
            if amt:
                lines.append({"section": "Add back", "description": f"{x['name']} - {x['treatment'].lower()}" + (f" ({pct}%)" if x["treatment"] == "Partly allowable" else ""),
                              "account": x["account"], "book_amount": x["net"], "amount": amt, "source": AUTO})
        elif x["root_type"] == "Income" and x["treatment"] == "Exempt income":
            lines.append({"section": "Deduction", "description": f"{x['name']} - exempt income", "account": x["account"], "book_amount": x["net"], "amount": x["net"], "source": AUTO})
    wht_codes = {r.code for r in load_rules(None, "WHT")}
    wht = sum((r["tax"] for r in ledger_rows(start, end) if r["section"] == "Input tax" and r["tax_code"].upper() in wht_codes), ZERO)
    return {"turnover": turnover, "expenses": expenses, "profit": turnover - expenses, "lines": lines, "wht": wht,
            "hash": _fp([str(turnover), str(expenses), [(l["account"], str(l["amount"])) for l in lines], str(wht)])}


def previous_loss(jurisdiction, start) -> Decimal:
    rows = get_list("Income Tax Computation", filters=[["docstatus", "=", 1], ["jurisdiction", "=", jurisdiction], ["period_end", "<", start]],
                    fields=["loss_carried_forward", "period_end"], order_by="period_end desc", limit=1, ignore_permissions=True)
    return _d(rows[0]["loss_carried_forward"]) if rows else ZERO


def _sum(doc, section):
    return sum((_d(l.amount) for l in doc.lines or [] if l.section == section), ZERO)


class IncomeTaxComputation(Document):
    def validate(self):
        if not self.period_start or not self.period_end or _date(self.period_start) > _date(self.period_end):
            throw("Enter a valid period: the start cannot be after the end.")
        on = _date(self.period_end)
        from velora_erp.tax.service import settings
        st = settings()
        self.jurisdiction = self.jurisdiction or st.get("default_jurisdiction")
        self.income_tax_rule = self.income_tax_rule or st.get("default_income_tax_rule")
        self.minimum_tax_rule = self.minimum_tax_rule or st.get("default_minimum_tax_rule")
        self.levy_rules = self.levy_rules or st.get("default_levy_rules")
        for i, l in enumerate(self.lines or [], 1):
            if _d(l.amount) < 0 and l.section != "Other":
                throw(f"Row {i}: enter a positive amount; the section decides whether it adds or reduces profit.")
        self.income_tax_rule = (self.income_tax_rule or "").strip().upper()
        self.minimum_tax_rule = (self.minimum_tax_rule or "").strip().upper() or None
        codes = [c.strip().upper() for c in str(self.levy_rules or "").replace("\n", ",").split(",") if c.strip()]
        self.levy_rules = ", ".join(codes) or None
        if not self.jurisdiction:
            throw("Choose the jurisdiction (or set a default in Tax Settings).")
        if not self.income_tax_rule:
            throw("Enter the income tax rule code (or set a default in Tax Settings).")
        rule, minimum = _rule(self.income_tax_rule, "Income Tax", on, "Income Tax"), _rule(self.minimum_tax_rule, "Income Tax", on, "minimum tax")
        levies = [_rule(c, "Levy", on, "Levy") for c in codes]
        profit = _d(self.accounting_profit)
        self.total_add_backs, self.total_deductions, self.total_capital_allowances = _sum(self, "Add back"), _sum(self, "Deduction"), _sum(self, "Capital allowance")
        other = _sum(self, "Other")
        self.adjusted_profit = profit + self.total_add_backs + other - self.total_deductions - self.total_capital_allowances
        bf = max(ZERO, _d(self.loss_brought_forward))
        if self.adjusted_profit <= 0:
            self.loss_relieved, self.assessable_profit, self.loss_carried_forward = ZERO, ZERO, bf - self.adjusted_profit
        else:
            self.loss_relieved = min(bf, self.adjusted_profit)
            self.assessable_profit, self.loss_carried_forward = self.adjusted_profit - self.loss_relieved, bf - self.loss_relieved
        self.income_tax = eng.calculate(rule, self.assessable_profit).tax_amount if self.assessable_profit > 0 else ZERO
        self.minimum_tax = eng.calculate(minimum, _d(self.turnover)).tax_amount if minimum and _d(self.turnover) > 0 else ZERO
        self.income_tax_charge = max(self.income_tax, self.minimum_tax)
        self.levies = sum((eng.calculate(r, self.assessable_profit).tax_amount for r in levies), ZERO) if self.assessable_profit > 0 else ZERO
        cap = min(_d(self.wht_available), self.income_tax_charge)
        if self.wht_utilised in (None, ""):
            self.wht_utilised = cap
        elif _d(self.wht_utilised) < 0 or _d(self.wht_utilised) > cap:
            throw(f"Withholding tax credit used cannot exceed {cap:,.2f} (the lower of the credits available and the income tax charged).")
        self.net_payable = self.income_tax_charge + self.levies - _d(self.wht_utilised)
        validate_approval_transition(self)

    def before_submit(self):
        if not self.calculated_on:
            throw("Calculate the computation from the ledger before submitting it.")
        if facts(_date(self.period_start), _date(self.period_end))["hash"] != self.source_hash:
            throw("The ledger has changed since this was calculated. Calculate again before submitting.")
        ensure_approved(self, required=True)


def calculate_computation(name: str) -> dict:
    doc = get_doc("Income Tax Computation", name)
    if doc.docstatus != 0:
        throw("Only a draft computation can be calculated. Cancel and amend a submitted one.")
    f = facts(_date(doc.period_start), _date(doc.period_end))
    manual = [l.as_dict() if hasattr(l, "as_dict") else dict(l) for l in doc.lines or [] if l.source != AUTO]
    doc.set("lines", f["lines"] + manual)
    doc.turnover, doc.total_expenses, doc.accounting_profit, doc.wht_available = f["turnover"], f["expenses"], f["profit"], f["wht"]
    if doc.loss_brought_forward in (None, "", 0):
        doc.loss_brought_forward = previous_loss(doc.jurisdiction, _date(doc.period_start))
    doc.wht_utilised = None
    doc.calculated_on = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    doc.source_hash = f["hash"]
    doc.save()
    return summary(doc)


def summary(doc) -> dict:
    keys = ["turnover", "total_expenses", "accounting_profit", "total_add_backs", "total_deductions", "total_capital_allowances", "adjusted_profit", "loss_brought_forward", "loss_relieved",
            "assessable_profit", "loss_carried_forward", "income_tax", "minimum_tax", "income_tax_charge", "levies", "wht_available", "wht_utilised", "net_payable"]
    return {"name": doc.name, **{k: str(_d(doc.get(k))) for k in keys}}
