from velora import Document, get_doc, throw
from velora_erp.finance.returns import validate_return, submit_return
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.finance.inventory.ledger import post_stock_movement

class SalesReturn(Document):
    def validate(self):
        validate_return(self, "Sales")
        disposition = getattr(self, "return_disposition", "Restock") or "Restock"
        if disposition not in ("Restock", "Quarantine"):
            throw("Select Restock or Quarantine as the return disposition.")
        if disposition == "Quarantine":
            if not self.warehouse:
                throw("A designated Quarantine Warehouse is required for quarantined returns.")
            warehouse = get_doc("Warehouse", self.warehouse)
            if not getattr(warehouse, "is_quarantine_warehouse", 0):
                throw("The selected Warehouse is not designated as a Quarantine Warehouse.")
        elif self.warehouse:
            warehouse = get_doc("Warehouse", self.warehouse)
            if getattr(warehouse, "is_quarantine_warehouse", 0):
                throw("A Quarantine Warehouse cannot be used for returns marked Restock.")
        validate_approval_transition(self)
    def before_submit(self):
        ensure_approved(self, required=True)
        if getattr(self, "return_disposition", "Restock") == "Restock" and getattr(self, "quality_inspection_required", 0):
            if getattr(self, "quality_inspection_status", "Pending") != "Passed" or not getattr(self, "inspection_reference", None):
                throw("A passed Quality Inspection Status and Inspection Reference are required before returned goods can be restocked.")
    def on_submit(self):
        submit_return(self, "Sales")
        post_stock_movement(source=self, posting_date=self.posting_date, warehouse=self.warehouse,
            lines=self.lines, direction=1, rate_field="valuation_rate", accounting_event="Sales Return",
            remarks=f"Sales Return {self.name}")
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted return cannot be deleted.")
