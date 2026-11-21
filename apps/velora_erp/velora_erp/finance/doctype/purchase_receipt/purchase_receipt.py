from velora import Document, get_doc, throw
from velora_erp.finance.operational_documents import validate_fulfilment
from velora_erp.finance.inventory.ledger import post_stock_movement

class PurchaseReceipt(Document):
    # An inspection stays on record when the document it inspected is cancelled.
    ignore_linked_doctypes = ("Quality Inspection",)
    def validate(self):
        validate_fulfilment(self, "Purchase Order", "Supplier")
        from velora_erp.finance.inventory.ledger import is_stock_item
        has_stock = any(is_stock_item(getattr(line, "item_code", None)) for line in self.lines or [])
        if has_stock and not self.warehouse:
            throw("Receiving Warehouse is required for stock-managed items.")
        if self.warehouse:
            warehouse = get_doc("Warehouse", self.warehouse)
            if warehouse.disabled or warehouse.is_group:
                throw("Select an active leaf Receiving Warehouse.")
    def before_submit(self):
        # two drafts can both pass validation; re-check against what has been submitted since
        from velora_erp.finance.operational_documents import check_not_over_fulfilled
        check_not_over_fulfilled(self, "Purchase Order")
        from velora_erp.finance.inventory.quality import require_inspections
        require_inspections(self, "inspection_required_on_receipt")
        self.document_status = "Completed"
    def on_submit(self):
        post_stock_movement(source=self, posting_date=self.document_date, warehouse=self.warehouse,
            lines=self.lines, direction=1, rate_field="valuation_rate", accounting_event="Purchase Receipt",
            remarks=self.narration or f"Purchase Receipt {self.name}")
        from velora_erp.finance.pricing import refresh_last_purchase_cost
        for item_code in {getattr(line, "item_code", None) for line in self.lines or [] if getattr(line, "item_code", None)}:
            refresh_last_purchase_cost(item_code)
        from velora_erp.finance.fulfilment import refresh_for
        refresh_for(self)                                                       # the order behind this receipt shows Received %
