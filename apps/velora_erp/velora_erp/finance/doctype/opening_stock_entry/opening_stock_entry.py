from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw
from velora_erp.finance.inventory.ledger import post_opening_stock_entry
from velora_erp.finance.source_documents import validate_approval_transition


class OpeningStockEntry(Document):
    def validate(self):
        if not self.posting_date or not self.items:
            throw("Opening Balance Date and at least one Opening Stock Line are required.")
        total_qty = Decimal("0")
        total_value = Decimal("0")
        for index, line in enumerate(self.items, 1):
            if not line.item_code or not line.warehouse:
                throw(f"Line {index}: Inventory Item and Warehouse are required.")
            try:
                quantity = Decimal(str(line.quantity or 0))
                rate = Decimal(str(line.valuation_rate or 0))
            except Exception:
                throw(f"Line {index}: Opening Quantity and Valuation Rate must be numeric.")
            if not quantity.is_finite() or not rate.is_finite() or quantity <= 0 or rate <= 0:
                throw(f"Line {index}: Opening Quantity and Valuation Rate must be finite and greater than zero.")
            line.amount = (quantity * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_qty += quantity
            total_value += line.amount
        self.total_quantity = total_qty
        self.total_value = total_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        validate_approval_transition(self)

    def before_submit(self):
        if self.approval_status != "Approved":
            throw("Opening Stock Entry requires independent approval by an authorised approver.")

    def on_submit(self):
        post_opening_stock_entry(self)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Opening Stock Entry cannot be deleted.")
