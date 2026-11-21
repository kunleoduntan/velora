from velora import Document, throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import (
    calculate_totals, ensure_approved, finance_settings, persist_posting_batch_link,
    posting_lines, validate_approval_transition,
)


class FinancialVoucher(Document):
    def validate(self):
        calculate_totals(self)
        validate_approval_transition(self)
        if not self.voucher_date or not self.posting_date:
            throw("Voucher Date and Posting Date are required.")
        if not self.narration or not str(self.narration).strip():
            throw("Voucher Narration is required.")
        settings = finance_settings()
        self.currency = (self.currency or settings["base_currency"]).upper()
        if not self.exchange_rate or float(self.exchange_rate) <= 0:
            throw("Exchange Rate must be greater than zero.")

    def before_submit(self):
        settings = finance_settings()
        ensure_approved(self, required=True)

    def on_submit(self):
        batch = post_financial_transaction(
            source_doctype=self.doctype,
            source_name=self.name,
            posting_date=self.posting_date,
            currency=self.currency,
            exchange_rate=self.exchange_rate,
            lines=posting_lines(self),
            posting_event="Adjustment",
            remarks=self.narration,
            idempotency_key=f"financial-voucher:{self.name}",
        )
        persist_posting_batch_link(self, batch)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Financial Voucher cannot be deleted.")
