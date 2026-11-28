from velora import Document, throw
from velora_erp.finance.inventory.ledger import close_weighted_average_period
from velora_erp.finance.source_documents import validate_approval_transition

class InventoryValuationClosing(Document):
    def validate(self):
        if not self.period_start or not self.period_end or self.period_start > self.period_end:
            throw("Enter a valid valuation period.")
        if self.posting_date != self.period_end:
            throw("Posting Date must equal Period End.")
        validate_approval_transition(self)
    def before_submit(self):
        if self.approval_status != "Approved":
            throw("Inventory Valuation Closing requires independent approval.")
    def on_submit(self):
        close_weighted_average_period(self)
def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Inventory Valuation Closing cannot be deleted.")
