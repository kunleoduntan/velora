from velora import Document, throw


class Customer(Document):
    def validate(self):
        self.customer_name = (self.customer_name or "").strip() or None
        if self.credit_limit is not None and self.credit_limit < 0:
            throw("Credit limit cannot be negative")
