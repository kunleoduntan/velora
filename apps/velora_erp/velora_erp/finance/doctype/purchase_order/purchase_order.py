from velora import Document, throw
from velora_erp.finance.operational_documents import validate_order
class PurchaseOrder(Document):
    def validate(self): validate_order(self, "Supplier")
    def before_submit(self): self.document_status = "Open"
