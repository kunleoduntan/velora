from velora import Document, get_doc, throw
from velora_erp.finance.source_documents import validate_approval_transition
from velora_erp.finance.inventory.ledger import post_stock_transfer

class StockTransfer(Document):
    def validate(self):
        if not self.posting_date or not self.source_warehouse or not self.target_warehouse:
            throw("Posting Date, Source Warehouse and Destination Warehouse are required.")
        if self.source_warehouse == self.target_warehouse:
            throw("Source and destination warehouses must be different.")
        for name in (self.source_warehouse, self.target_warehouse):
            warehouse = get_doc("Warehouse", name)
            if warehouse.disabled or warehouse.is_group:
                throw("Select active leaf warehouses for Stock Transfer.")
        if not self.lines:
            throw("Add at least one Stock Transfer line.")
        from velora_erp.finance.inventory.transit import validate_transfer
        validate_transfer(self)
        validate_approval_transition(self)
    def before_submit(self):
        if self.approval_status != "Approved":
            throw("Stock Transfer requires independent approval by an authorised approver.")
        self.transit_status = "In Transit" if self.transit_warehouse else "Direct"
    def on_submit(self):
        post_stock_transfer(self, target_warehouse=self.transit_warehouse or None)
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Stock Transfer cannot be deleted.")
