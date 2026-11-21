from velora import Document, throw
from velora_erp.finance.inventory import cycle_count


class CycleCount(Document):
    def validate(self):
        if not self.warehouse:
            throw("Choose the warehouse to count.")
        seen = set()
        for i, ln in enumerate(self.lines or [], 1):
            key = (ln.item_code, ln.batch or None)
            if key in seen:
                throw(f"Line {i}: {ln.item_code} appears twice on this count.")
            seen.add(key)
            if ln.counted_qty not in (None, ""):
                if float(ln.counted_qty) < 0:
                    throw(f"Line {i}: counted quantity cannot be negative.")
                ln.variance = float(ln.counted_qty) - float(ln.system_qty or 0)
            else:
                ln.variance = None
        if self.status == "Posted" and not self.stock_reconciliation:
            throw("A posted count must link to its Stock Reconciliation.")

    def generate_sheet(self):
        n = cycle_count.generate(self)
        self.save()
        return n

    def post_count(self):
        rec = cycle_count.post(self)
        self.save()
        return rec.name

    def before_delete(self):
        if self.status == "Posted":
            throw("A posted Cycle Count cannot be deleted.")
