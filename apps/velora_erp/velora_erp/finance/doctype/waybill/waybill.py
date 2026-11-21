from velora import Document, get_doc, throw
from velora_erp.finance.operational_documents import validate_waybill
class Waybill(Document):
    def validate(self):
        validate_waybill(self)
        note = get_doc("Delivery Note", self.delivery_note)
        if int(note.docstatus or 0) != 1: throw("Waybill can only be prepared from a submitted Delivery Note.")
        if note.party != self.party: throw("Waybill Customer must match the Delivery Note Customer.")
    def before_submit(self): self.document_status = "Completed"
