from velora import Document, throw
from velora_erp.finance.inventory.ledger import prepare_stock_revaluation, submit_stock_revaluation
from velora_erp.finance.source_documents import validate_approval_transition

class StockRevaluation(Document):
    def validate(self):
        prepare_stock_revaluation(self)
        validate_approval_transition(self)
    def before_submit(self):
        if self.approval_status != "Approved":
            throw("Stock Revaluation requires independent approval.")
    def on_submit(self):
        submit_stock_revaluation(self)
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Stock Revaluation cannot be deleted.")
