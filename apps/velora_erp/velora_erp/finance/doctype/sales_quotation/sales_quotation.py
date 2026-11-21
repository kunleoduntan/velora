from datetime import date
from velora import Document, throw
from velora_erp.finance.operational_documents import validate_order
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved


class SalesQuotation(Document):
    def validate(self):
        from velora_erp.finance.pricing import apply_sales_pricing, enforce_cost_floor
        if not self.document_date or not self.valid_until:
            throw("Quotation Date and Valid Until are required.")
        if str(self.valid_until) < str(self.document_date):
            throw("Valid Until cannot be earlier than Quotation Date.")
        validate_approval_transition(self)
        apply_sales_pricing(self, "Sales Quotation")
        validate_order(self, "Customer")
        from decimal import Decimal
        self.total_amount = sum((Decimal(str(getattr(line, "amount", 0) or 0)) for line in self.lines or []), Decimal("0"))
        enforce_cost_floor(self, "Sales Quotation")

    def before_submit(self):
        ensure_approved(self, required=True)
        if str(self.valid_until) < date.today().isoformat():
            throw("This quotation has expired. Create a revised quotation with a new validity period and obtain independent approval.")
        self.document_status = "Open"

