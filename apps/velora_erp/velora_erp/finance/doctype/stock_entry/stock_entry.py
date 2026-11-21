from datetime import datetime
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now


class StockEntry(Document):
    # An inspection stays on record when the document it inspected is cancelled.
    ignore_linked_doctypes = ("Quality Inspection",)
    def validate(self):
        if not self.lines: throw("Add at least one item.")
        if self.stock_entry_type != "Material Receipt" and self.source_account: self.source_account = None
        for i, ln in enumerate(self.lines, 1):
            if float(ln.quantity or 0) <= 0: throw(f"Line {i}: quantity must be greater than zero.")
            if self.stock_entry_type == "Material Receipt" and float(ln.basic_rate or 0) < 0: throw(f"Line {i}: the rate cannot be negative.")
        if self.entry_status == "Approved" and decided_now(self, "entry_status"):
            self.approved_by = get_session().user; self.approved_on = datetime.utcnow().replace(microsecond=0)

    def on_submit(self):
        from velora_erp.finance.inventory.requests import post_stock_entry, refresh_fulfilment
        post_stock_entry(self)
        if self.material_request: refresh_fulfilment(self.material_request)


    def before_delete(self):
        if self.docstatus == 1: throw("A submitted Stock Entry cannot be deleted.")
