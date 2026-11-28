from velora import Document
from velora_erp.finance.cash_transactions import validate_cash_document, submit_cash_document, ensure_approved
from velora_erp.finance.source_documents import validate_approval_transition
from velora import throw

class Receipt(Document):
    # Cancelling this document unlinks or removes these by itself (see finance/cancellation.py), so they do not block it.
    ignore_linked_doctypes = ("Recognition Schedule", "Schedule Recognition")

    def validate(self):
        validate_cash_document(self, "Receipt")
    def before_submit(self):
        ensure_approved(self, required=True)
    def on_submit(self):
        submit_cash_document(self, "Receipt")
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Receipt cannot be deleted.")
