from decimal import Decimal

from velora import Document, get_doc, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, persist_posting_batch_link, validate_approval_transition
from velora_erp.finance.validation import row
from velora_erp.treasury import service as svc
from velora_erp.treasury.engine import money

D = svc.D


class FinancingDrawdown(Document):
    def validate(self):
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        if fac.docstatus != 1 or fac.status != "Active":
            throw("Money can only be drawn on an active, approved facility.")
        d = svc.as_date(self.drawdown_date)
        if not d or d < svc.as_date(fac.start_date) or d > svc.as_date(fac.expiry_date):
            throw(f"The drawdown date must fall between {fac.start_date} and {fac.expiry_date}, the period the facility is available.")
        amount = D(self.amount)
        if amount <= 0:
            throw("The amount drawn must be greater than zero.")
        if self.docstatus == 0:
            room = svc.facility_available(fac)
            if amount > room:
                throw(f"This drawdown of {amount:,.2f} is more than the {room:,.2f} still available under {fac.facility_name}.")
        self.currency = fac.currency
        if fac.currency != svc.base_currency():
            if not self.exchange_rate or float(self.exchange_rate) == 1:
                rate = svc.rate_for(fac.currency, d)
                if rate is None:
                    throw(f"Enter the exchange rate: none is recorded for {fac.currency}.")
                self.exchange_rate = float(rate)
        else:
            self.exchange_rate = 1
        if float(self.exchange_rate or 0) <= 0:
            throw("The exchange rate must be greater than zero.")
        bank = row("Account", self.bank_account, "name", "disabled", "is_group", "root_type")
        if not bank or bank["disabled"] or bank["is_group"] or bank["root_type"] != "Asset":
            throw("Choose the active bank account that receives the money.")
        for f, src in (("interest_rate", "interest_rate"), ("repayment_structure", "repayment_structure"), ("repayment_frequency", "repayment_frequency"),
                       ("tenor_months", "default_tenor_months"), ("grace_period_months", "grace_period_months")):
            if getattr(self, f) in (None, "", 0) and f != "grace_period_months":
                setattr(self, f, getattr(fac, src))
        self.interest_rate_type, self.day_count_basis = fac.interest_rate_type, fac.day_count_basis
        if int(self.grace_period_months or 0) == 0:
            self.grace_period_months = fac.grace_period_months or 0
        fee = D(self.arrangement_fee)
        if fee <= 0 and float(fac.arrangement_fee_percent or 0) > 0:
            fee = money(amount * D(fac.arrangement_fee_percent) / 100)
        if fee < 0 or fee >= amount:
            throw("The arrangement fee must be less than the amount drawn.")
        self.arrangement_fee = fee
        self.title = f"{fac.facility_name} - {amount:,.2f} {fac.currency}"
        if self.docstatus == 0:
            try:
                self.set("schedule", svc.schedule_rows(self))
            except ValueError as e:
                throw(str(e))
            self.maturity_date = self.schedule[-1].due_date if self.schedule else None
            self.outstanding_principal = amount
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        room = svc.facility_available(fac)
        if D(self.amount) > room:
            throw(f"This drawdown of {D(self.amount):,.2f} is more than the {room:,.2f} still available under {fac.facility_name}.")

    def on_submit(self):
        fac = get_doc("Financing Facility", self.facility, ignore_permissions=True)
        amount, fee = D(self.amount), D(self.arrangement_fee)
        lines = [{"account": self.bank_account, "debit": amount - fee, "credit": 0, "line_description": f"Loan drawn: {fac.facility_name}"}]
        if fee:
            lines.append({"account": fac.fee_expense_account, "debit": fee, "credit": 0, "line_description": f"Arrangement fee: {fac.facility_name}"})
        lines.append({"account": fac.loan_liability_account, "debit": 0, "credit": amount, "line_description": f"Loan: {fac.facility_name} ({self.name})"})
        batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.drawdown_date, currency=self.currency, exchange_rate=self.exchange_rate,
                                           lines=lines, posting_event="Original", remarks=self.narration or f"Drawdown {self.name}", idempotency_key=f"financing-drawdown:{self.name}")
        persist_posting_batch_link(self, batch)
        db_update(self, status="Active", outstanding_principal=amount, interest_accrued_to=self.drawdown_date, accrued_interest_balance=0)
        svc.refresh_facility(self.facility)

    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted drawdown cannot be deleted; cancel it instead.")


def on_cancelled(doc, report):
    svc.refresh_facility(doc.facility)
