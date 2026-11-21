from velora import Document, throw
from velora_erp.finance.landed_cost import validate_landed_cost_voucher
from velora_erp.finance.inventory.ledger import capitalize_landed_cost
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved

class LandedCostVoucher(Document):
    def validate(self):
        validate_landed_cost_voucher(self)
        validate_approval_transition(self)
    def before_submit(self):
        ensure_approved(self, required=True)
    def on_submit(self):
        capitalize_landed_cost(self)
        from velora_erp.finance.pricing import refresh_last_purchase_cost
        receipt = __import__("velora").get_doc("Purchase Receipt", self.purchase_receipt)
        for item_code in {getattr(line, "item_code", None) for line in receipt.lines or [] if getattr(line, "item_code", None)}:
            refresh_last_purchase_cost(item_code)
    def before_delete(self):
        if self.docstatus == 1: throw("A submitted Landed Cost Voucher cannot be deleted.")
