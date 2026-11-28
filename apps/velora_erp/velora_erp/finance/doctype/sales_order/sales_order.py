from decimal import Decimal
from velora import Document, throw
from velora_erp.finance.operational_documents import validate_order

class SalesOrder(Document):
    def validate(self):
        from velora_erp.finance.pricing import apply_sales_pricing, enforce_cost_floor
        apply_sales_pricing(self, "Sales Order")
        validate_order(self, "Customer")
        enforce_cost_floor(self, "Sales Order")
        if getattr(self, "source_doctype", None) == "Sales Quotation" and getattr(self, "source_document", None):
            from velora_erp.finance.operational_documents import check_not_over_fulfilled
            check_not_over_fulfilled(self, "Sales Quotation")
    def before_submit(self):
        if getattr(self, "source_doctype", None) == "Sales Quotation" and getattr(self, "source_document", None):
            from velora_erp.finance.operational_documents import check_not_over_fulfilled
            check_not_over_fulfilled(self, "Sales Quotation")
        from velora_erp.finance.credit_control import enforce_customer_credit
        from velora_erp.finance.credit_control import order_gross_total
        order_value = order_gross_total(self)
        exchange_rate = Decimal(str(getattr(self, "exchange_rate", 1) or 1))
        enforce_customer_credit(self, transaction_amount=Decimal(str(order_value or 0)) * exchange_rate)
        self.document_status = "Open"
