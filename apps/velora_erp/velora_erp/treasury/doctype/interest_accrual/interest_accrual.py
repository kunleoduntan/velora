from datetime import date
from decimal import Decimal

from velora import Document, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, persist_posting_batch_link, validate_approval_transition
from velora_erp.treasury import service as svc

D = svc.D


class InterestAccrual(Document):
    def validate(self):
        through = svc.as_date(self.accrual_date)
        if not through or through > date.today():
            throw("Interest cannot be accrued beyond today.")
        self.currency = (self.currency or svc.base_currency()).upper()
        if self.currency != svc.base_currency():
            if not self.exchange_rate or float(self.exchange_rate) == 1:
                rate = svc.rate_for(self.currency, through)
                if rate is None:
                    throw(f"Enter the exchange rate: none is recorded for {self.currency}.")
                self.exchange_rate = float(rate)
        else:
            self.exchange_rate = 1
        if self.docstatus == 0:
            self.set("lines", svc.accrual_lines(self.currency, through, self.facility or None))
            if not self.lines:
                throw("There is no interest to accrue for these loans up to that date.")
        self.total_interest = sum((D(l.interest) for l in self.lines), Decimal(0))
        self.title = f"Interest to {through} ({self.currency}) {self.total_interest:,.2f}"
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        from velora import get_doc
        by = {}
        for l in self.lines:
            by[l.facility] = by.get(l.facility, Decimal(0)) + D(l.interest)
        lines = []
        for fac_name, amt in by.items():
            fac = get_doc("Financing Facility", fac_name, ignore_permissions=True)
            lines.append({"account": fac.interest_expense_account, "debit": amt, "credit": 0, "line_description": f"Interest accrued: {fac.facility_name}"})
            lines.append({"account": fac.accrued_interest_account, "debit": 0, "credit": amt, "line_description": f"Interest accrued: {fac.facility_name}"})
        batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.accrual_date, currency=self.currency, exchange_rate=self.exchange_rate,
                                           lines=lines, posting_event="Original", remarks=self.narration or f"Interest accrual {self.name}", idempotency_key=f"interest-accrual:{self.name}")
        persist_posting_batch_link(self, batch)
        for dd in {l.drawdown for l in self.lines}:
            svc.refresh_drawdown(dd)
        for fac in by:
            svc.refresh_facility(fac)

    def before_cancel(self):
        for dd in {l.drawdown for l in self.lines}:
            last = max(svc.as_date(l.to_date) for l in self.lines if l.drawdown == dd)
            current = svc.as_date(svc.get_doc("Financing Drawdown", dd, ignore_permissions=True).interest_accrued_to)
            if current and current > last:
                throw(f"A later interest accrual exists for {dd}; cancel that one first.")

    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted accrual cannot be deleted; cancel it instead.")


def on_cancelled(doc, report):
    for dd in {l.drawdown for l in doc.lines}:
        svc.refresh_drawdown(dd)
    for fac in {l.facility for l in doc.lines}:
        svc.refresh_facility(fac)
