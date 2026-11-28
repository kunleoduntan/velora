from velora import Document, get_doc, throw
from velora_erp.finance.operational_documents import validate_waybill
class Waybill(Document):
    def validate(self):
        validate_waybill(self)
        if self.delivery_note:
            src, label = get_doc("Delivery Note", self.delivery_note), "Delivery Note"
        else:
            src, label = get_doc(self.source_doctype, self.source_document), self.source_doctype
        if int(src.docstatus or 0) != 1: throw(f"Waybill can only be prepared from a submitted {label}.")
        if src.party != self.party: throw(f"Waybill Customer must match the {label} Customer.")
    def before_submit(self): self.document_status = "Completed"
