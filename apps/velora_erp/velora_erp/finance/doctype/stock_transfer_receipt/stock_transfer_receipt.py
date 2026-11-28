from velora import Document, throw
from velora_erp.finance.source_documents import validate_approval_transition
from velora_erp.finance.inventory.ledger import post_stock_transfer
from velora_erp.finance.inventory import transit


class StockTransferReceipt(Document):
    def validate(self):
        if int(self.docstatus or 0) == 0:
            transit.validate_receipt(self)
        validate_approval_transition(self)

    def before_submit(self):
        if self.approval_status != "Approved":
            throw("This receipt is waiting for approval. It can be submitted once its approval workflow approves it.")
        transit.validate_receipt(self)                       # what is still in transit may have changed since this draft was saved

    def on_submit(self):
        post_stock_transfer(self, source_warehouse=self.transit_warehouse, target_warehouse=self.target_warehouse, lines=self.lines)
        transit.record_receipt(self)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Stock Transfer Receipt cannot be deleted.")
