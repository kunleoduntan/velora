from velora import Document, throw


class Customer(Document):
    def validate(self):
        self.customer_name = (self.customer_name or "").strip() or None
        if (self.credit_days or 0) < 0:
            throw("Payment terms cannot be negative")
