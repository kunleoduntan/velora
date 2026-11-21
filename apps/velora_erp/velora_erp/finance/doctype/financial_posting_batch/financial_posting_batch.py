from velora import Document, throw
from velora_erp.finance.engine import prepare_batch, _write_ledger


class FinancialPostingBatch(Document):
    def validate(self):
        prepare_batch(self)

    def before_submit(self):
        self.posting_status = "Posted"

    def on_submit(self):
        # Document.submit wraps this hook in the same transaction as the batch status change.
        # Any ledger insert failure therefore rolls the entire posting back.
        _write_ledger(self)

    def before_cancel(self):
        throw("A posted Financial Posting Batch cannot be cancelled. It goes only when the document that produced it is cancelled.")

    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted Financial Posting Batch is immutable and cannot be deleted.")
