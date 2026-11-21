from datetime import date

from velora import Document, get_doc, throw
from velora_erp.finance.inventory import reservations


class StockReservation(Document):
    def validate(self):
        if not self.item_code or not self.warehouse:
            throw("Item and Warehouse are required.")
        item = get_doc("Inventory Item", self.item_code)
        if item.disabled or not item.is_stock_item:
            throw("Only an active stock item can be reserved.")
        wh = get_doc("Warehouse", self.warehouse)
        if wh.disabled or wh.is_group:
            throw("Reserve stock in an active leaf Warehouse.")
        qty = float(self.quantity or 0)
        if qty <= 0:
            throw("Reserved quantity must be greater than zero.")
        used = float(self.consumed_quantity or 0)
        if used < 0 or used > qty:
            throw("Used quantity must be between zero and the reserved quantity.")
        if self.reserved_until and str(self.reserved_until)[:10] < date.today().isoformat() and self.is_new():
            throw("The hold date is already past.")
        if not self.status:
            self.status = "Active"
        if self.status == "Active":
            free = float(reservations.available(self.item_code, self.warehouse, self.batch or None, ignore_name=None if self.is_new() else self.name))
            if qty - used > free:
                throw(f"Only {max(free, 0)} of {self.item_code} is available in {self.warehouse}; {qty - used} cannot be reserved.")

    def before_delete(self):
        if float(self.consumed_quantity or 0) > 0:
            throw("Part of this reservation has already been used. Release it instead of deleting it.")
