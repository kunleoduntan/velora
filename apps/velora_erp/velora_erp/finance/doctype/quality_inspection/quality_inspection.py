from velora import Document, get_doc, throw
from velora_erp.finance.inventory import quality


class QualityInspection(Document):
    def validate(self):
        if int(self.docstatus or 0) == 0:
            quality.check_reference(self)
        quality.prepare(self)

    def before_submit(self):
        quality.require_complete(self)

    def before_cancel(self):
        ref = get_doc(self.reference_doctype, self.reference_name)
        if int(ref.docstatus or 0) == 1:
            throw(f"{self.reference_doctype} {self.reference_name} was submitted on the strength of this inspection, so it cannot be cancelled.")
