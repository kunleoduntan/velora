from velora import Document, throw
from velora_erp.finance.returns import validate_return, submit_return
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.finance.inventory.ledger import post_stock_movement

class PurchaseReturn(Document):
    def validate(self):
        validate_return(self, "Purchase")
        validate_approval_transition(self)
    def before_submit(self):
        ensure_approved(self, required=True)
    def on_submit(self):
        submit_return(self, "Purchase")
        post_stock_movement(source=self, posting_date=self.posting_date, warehouse=self.warehouse,
            lines=self.lines, direction=-1, accounting_event="Purchase Return",
            remarks=f"Purchase Return {self.name}")
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted return cannot be deleted.")
