from velora import Document, throw
from velora_erp.finance.inventory.ledger import prepare_reconciliation, submit_reconciliation
from velora_erp.finance.source_documents import validate_approval_transition

class StockReconciliation(Document):
    def validate(self):
        prepare_reconciliation(self)
        validate_approval_transition(self)
    def before_submit(self):
        if self.approval_status != "Approved":
            throw("Stock Reconciliation requires independent approval by an authorised approver.")
    def on_submit(self):
        submit_reconciliation(self)
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Stock Reconciliation cannot be deleted.")
