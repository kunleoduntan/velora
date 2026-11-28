from velora import Document, throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import (
    calculate_totals, ensure_approved, ensure_balance_sheet_accounts, finance_settings,
    persist_posting_batch_link, posting_lines, validate_approval_transition,
)


class OpeningBalanceEntry(Document):
    def validate(self):
        settings = finance_settings()
        self.currency = settings["base_currency"].upper()
        self.exchange_rate = 1
        calculate_totals(self)
        ensure_balance_sheet_accounts(self)
        validate_approval_transition(self)
        if not self.opening_date:
            throw("Opening Balance Date is required.")
        if not self.migration_reference or not str(self.migration_reference).strip():
            throw("Migration Reference is required.")
        if not self.narration or not str(self.narration).strip():
            throw("Migration Notes are required.")

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        batch = post_financial_transaction(
            source_doctype=self.doctype,
            source_name=self.name,
            posting_date=self.opening_date,
            currency=self.currency,
            exchange_rate=1,
            lines=posting_lines(self),
            posting_event="Opening Balance",
            remarks=f"{self.migration_reference}: {self.narration}",
            idempotency_key=f"opening-balance:{self.migration_reference}",
        )
        persist_posting_batch_link(self, batch)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Opening Balance Entry cannot be deleted.")
