from decimal import Decimal, InvalidOperation
from velora import Document, throw


class PaymentTerms(Document):
    def validate(self):
        self.terms_code = (self.terms_code or "").strip().upper()
        self.terms_name = (self.terms_name or "").strip()
        if not self.terms_code or not self.terms_name:
            throw("Payment Terms Code and Name are required.")
        for field in ("due_days", "discount_days"):
            value = getattr(self, field, 0) or 0
            if int(value) < 0:
                throw(f"{field.replace('_', ' ').title()} cannot be negative.")
        try:
            discount = Decimal(str(self.discount_percentage or 0))
        except (InvalidOperation, ValueError):
            throw("Discount Percentage must be a valid number.")
        if discount < 0 or discount > 100:
            throw("Discount Percentage must be between 0 and 100.")
        if discount and not self.discount_days:
            throw("Discount Days are required when an early payment discount is configured.")
        if self.discount_days and int(self.discount_days) > int(self.due_days or 0):
            throw("Early Payment Discount Days cannot exceed Invoice Due Days.")
