from velora import Document, throw


class Supplier(Document):
    def validate(self):
        self.supplier_name = (self.supplier_name or "").strip() or None
        if (self.credit_days or 0) < 0:
            throw("Payment terms cannot be negative")
