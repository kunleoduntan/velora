from decimal import Decimal

from velora import Document, get_doc, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, persist_posting_batch_link, validate_approval_transition
from velora_erp.finance.validation import row
from velora_erp.tax import engine as eng
from velora_erp.tax.wht import _rule_account, _rule_for
from velora_erp.treasury import service as svc
from velora_erp.treasury.engine import money

D = svc.D
ZERO = Decimal(0)


def due_amounts(drawdown, on):
    """Unpaid principal and interest of the instalments due on or before `on` (or of the next one when none is due yet)."""
    lines = [l for l in svc._lines(drawdown) if D(l["principal_paid"]) < D(l["principal_due"]) or D(l["interest_paid"]) < D(l["interest_due"])]
    due = [l for l in lines if svc.as_date(l["due_date"]) <= on] or lines[:1]
    return (sum((D(l["principal_due"]) - D(l["principal_paid"]) for l in due), ZERO), sum((D(l["interest_due"]) - D(l["interest_paid"]) for l in due), ZERO))


class FinancingRepayment(Document):
    def validate(self):
        dd = get_doc("Financing Drawdown", self.drawdown, ignore_permissions=True)
        if dd.docstatus != 1:
            throw("Choose a submitted drawdown.")
        fac = get_doc("Financing Facility", dd.facility, ignore_permissions=True)
        on = svc.as_date(self.repayment_date)
        if not on or on < svc.as_date(dd.drawdown_date):
            throw("The payment date cannot be before the drawdown date.")
        self.facility, self.currency = dd.facility, dd.currency
        self.exchange_rate = float(self.exchange_rate or dd.exchange_rate or 1) if dd.currency != svc.base_currency() else 1
        if self.docstatus == 0:
            fresh = svc.refresh_drawdown(dd.name) or dd
        else:
            fresh = dd
        p, i, f = D(self.principal_amount), D(self.interest_amount), D(self.fees_amount)
        if p == 0 and i == 0 and f == 0:
            p, i = due_amounts(dd.name, on)
            if p == 0 and i == 0:
                throw("Nothing is due on this loan; enter the amounts to pay.")
        if min(p, i, f) < 0:
            throw("Amounts cannot be negative.")
        if p > D(fresh.outstanding_principal):
            throw(f"The principal paid ({p:,.2f}) is more than the {D(fresh.outstanding_principal):,.2f} outstanding on this loan.")
        self.principal_amount, self.interest_amount, self.fees_amount = p, i, f
        bank = row("Account", self.bank_account, "name", "disabled", "is_group", "root_type")
        if not bank or bank["disabled"] or bank["is_group"] or bank["root_type"] != "Asset":
            throw("Choose the active bank account the payment is made from.")
        rule = None
        if not self.wht_exempt and i > 0:
            lender = row("Financial Institution", fac.financial_institution, "name", "wht_applicable")
            rule = (self.interest_wht_rule or fac.wht_rule or (svc.settings()["default_interest_wht_rule"] if lender and lender["wht_applicable"] else None) or "").strip().upper() or None
        wht = ZERO
        if rule:
            r = _rule_for(rule, on)
            if not r:
                throw(f"No approved withholding tax rule {rule} is in force on {on}.")
            wht = money(eng.calculate(r, i).tax_amount)
            self.tax_account = _rule_account(rule)
            ta = row("Account", self.tax_account, "name", "disabled", "is_group", "root_type") if self.tax_account else None
            if not ta or ta["disabled"] or ta["is_group"] or ta["root_type"] != "Liability":
                throw(f"The tax rule {rule} needs a tax payable (liability) account.")
        self.interest_wht_rule, self.wht_amount = rule, wht
        self.total_cost = p + i + f
        self.net_paid = self.total_cost - wht
        if self.docstatus == 0:
            self.accrued_interest_cleared = min(i, max(ZERO, D(fresh.accrued_interest_balance)))
        self.title = f"{dd.title or dd.name} - {self.total_cost:,.2f}"
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        dd = svc.refresh_drawdown(self.drawdown)
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        p, i, f, wht = D(self.principal_amount), D(self.interest_amount), D(self.fees_amount), D(self.wht_amount)
        if D(dd.outstanding_principal) < 0:                                  # the refresh already counts this payment
            throw(f"The principal paid ({p:,.2f}) is more than was outstanding on this loan.")
        cleared = min(i, D(self.accrued_interest_cleared or 0))
        label = f"{fac.facility_name} ({self.drawdown})"
        lines = []
        if p:
            lines.append({"account": fac.loan_liability_account, "debit": p, "credit": 0, "line_description": f"Loan principal repaid: {label}"})
        if cleared:
            lines.append({"account": fac.accrued_interest_account, "debit": cleared, "credit": 0, "line_description": f"Accrued interest settled: {label}"})
        if i - cleared:
            lines.append({"account": fac.interest_expense_account, "debit": i - cleared, "credit": 0, "line_description": f"Interest: {label}"})
        if f:
            lines.append({"account": fac.fee_expense_account, "debit": f, "credit": 0, "line_description": f"Fees and charges: {label}"})
        if wht:
            rule = _rule_for(self.interest_wht_rule, svc.as_date(self.repayment_date))
            x = Decimal(str(self.exchange_rate))
            lines.append({"account": self.tax_account, "debit": 0, "credit": wht, "line_description": f"WHT on interest {label}", "tax_jurisdiction": rule.jurisdiction if rule else None,
                          "tax_code": self.interest_wht_rule, "tax_rate": float(rule.rate) if rule else 0, "taxable_amount": i, "tax_amount": wht, "base_taxable_amount": i * x, "base_tax_amount": wht * x})
        lines.append({"account": self.bank_account, "debit": 0, "credit": D(self.net_paid), "line_description": f"Paid to {label}"})
        batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.repayment_date, currency=self.currency, exchange_rate=self.exchange_rate,
                                           lines=lines, posting_event="Original", remarks=self.narration or f"Loan repayment {self.name}", idempotency_key=f"financing-repayment:{self.name}")
        persist_posting_batch_link(self, batch)
        db_update(self, accrued_interest_cleared=cleared)
        svc.refresh_drawdown(self.drawdown)
        svc.refresh_facility(self.facility)

    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted repayment cannot be deleted; cancel it instead.")


def on_cancelled(doc, report):
    svc.refresh_drawdown(doc.drawdown)
    svc.refresh_facility(doc.facility)
