from decimal import Decimal

from velora import Document, get_doc, throw


class SalesOrder(Document):
    def validate(self):
        total = Decimal("0")
        for row in self.items:
            if row.qty is not None and row.qty <= 0:
                throw(f"Row {row.idx}: quantity must be positive")
            if row.rate is not None:
                row.amount = (Decimal(str(row.qty)) * row.rate).quantize(Decimal("0.01"))
                total += row.amount
        self.total = total

    def before_submit(self):
        # internal lookup: a Sales User may submit orders even without rights to edit customers
        if get_doc("Customer", self.customer, ignore_permissions=True).status == "Blocked":
            throw("Cannot submit an order for a blocked customer")
