from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now


class MaterialRequest(Document):
    def validate(self):
        lines = list(self.lines or [])
        if not lines: throw("Add at least one item to the request.")
        seen = set(); total_q = 0.0; total_v = 0.0
        for i, ln in enumerate(lines, 1):
            if not ln.item_code: throw(f"Line {i}: choose an item.")
            q = float(ln.quantity or 0)
            if q <= 0: throw(f"Line {i}: quantity must be greater than zero.")
            if ln.item_code in seen: throw(f"Line {i}: {ln.item_code} is already on this request; combine the quantities.")
            seen.add(ln.item_code)
            total_q += q; total_v += q * float(ln.estimated_rate or 0)
        self.total_quantity = round(total_q, 6); self.estimated_total = round(total_v, 2)
        if self.request_type == "Material Transfer":
            if not self.source_warehouse or not self.target_warehouse: throw("A transfer request needs a source and a target warehouse.")
            if self.source_warehouse == self.target_warehouse: throw("Source and target warehouse must be different.")
        if self.request_type == "Material Issue" and not self.source_warehouse: throw("An issue request needs the warehouse to issue from.")
        if self.required_by and self.request_date and str(self.required_by)[:10] < str(self.request_date)[:10]:
            throw("Required By cannot be earlier than the request date.")
        if self.request_status == "Approved" and decided_now(self, "request_status"):
            self.approved_by = get_session().user; self.approved_on = datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)

    def on_update(self):
        if self.name and not self.is_new():
            from velora_erp.finance.inventory.requests import refresh_fulfilment
            refresh_fulfilment(self.name)
