from velora import Document, get_doc, throw
from velora_erp.finance.operational_documents import validate_fulfilment
from velora_erp.finance.inventory.ledger import post_stock_movement

class DeliveryNote(Document):
    # An inspection stays on record when the document it inspected is cancelled.
    ignore_linked_doctypes = ("Quality Inspection",)
    def validate(self):
        validate_fulfilment(self, "Sales Order", "Customer")
        from velora_erp.finance.pricing import enforce_cost_floor
        enforce_cost_floor(self, "Delivery Note")
        from velora_erp.finance.inventory.ledger import is_stock_item
        has_stock = any(is_stock_item(getattr(line, "item_code", None)) for line in self.lines or [])
        if has_stock and not self.warehouse:
            throw("Dispatch Warehouse is required for stock-managed items.")
        if self.warehouse:
            warehouse = get_doc("Warehouse", self.warehouse)
            if warehouse.disabled or warehouse.is_group:
                throw("Select an active leaf Dispatch Warehouse.")
    def before_submit(self):
        # two drafts can both pass validation; re-check against what has been submitted since
        from velora_erp.finance.operational_documents import check_not_over_fulfilled
        check_not_over_fulfilled(self, "Sales Order")
        from velora_erp.finance.inventory.quality import require_inspections
        require_inspections(self, "inspection_required_on_delivery")
        self.document_status = "Completed"
    def on_submit(self):
        from velora_erp.finance.pricing import enforce_delivery_issue_cost_floor
        enforce_delivery_issue_cost_floor(self)
        post_stock_movement(source=self, posting_date=self.document_date, warehouse=self.warehouse,
            lines=self.lines, direction=-1, accounting_event="Delivery Note",
            remarks=self.narration or f"Delivery Note {self.name}")
        from velora_erp.finance.fulfilment import refresh_for
        refresh_for(self)                                                       # the order behind this delivery shows Delivered %
