from decimal import Decimal
from velora import Document, throw
from velora_erp.finance.invoices import validate_invoice, submit_invoice
from velora_erp.finance.source_documents import ensure_approved

class SalesInvoice(Document):
    # Cancelling this document unlinks or removes these by itself (see finance/cancellation.py), so they do not block it.
    ignore_linked_doctypes = ("Recognition Schedule", "Schedule Recognition", "Receipt", "Payment")

    def validate(self):
        from velora_erp.finance.pricing import apply_sales_pricing, enforce_cost_floor
        apply_sales_pricing(self, "Sales Invoice")
        validate_invoice(self, "Sales")
        from velora_erp.finance.fulfilment import check_not_over_billed
        check_not_over_billed(self, source_doctype="Sales Order")
        check_not_over_billed(self, source_doctype="Delivery Note")
        enforce_cost_floor(self, "Sales Invoice")
        if getattr(self, "update_stock", 0):
            if getattr(self, "source_doctype", None) == "Sales Order":
                throw("Update Stock cannot be used on an invoice raised from a Sales Order: deliver those goods with a Delivery Note, otherwise cost of goods sold is posted twice.")
            if not getattr(self, "warehouse", None):
                throw("Select the Dispatch Warehouse when Update Stock is on.")
    def before_submit(self):
        ensure_approved(self, required=True)
        from velora_erp.finance.credit_control import enforce_customer_credit
        base_amount = Decimal(str(self.grand_total or 0)) * Decimal(str(getattr(self, "exchange_rate", 1) or 1))
        enforce_customer_credit(self, transaction_amount=base_amount, include_orders=True)
    def on_submit(self):
        submit_invoice(self, "Sales")
        if getattr(self, "update_stock", 0):
            from velora_erp.finance.inventory.ledger import post_stock_movement
            post_stock_movement(source=self, posting_date=self.posting_date, warehouse=self.warehouse, lines=self.lines, direction=-1,
                                accounting_event="Delivery Note", remarks=f"Delivered by Sales Invoice {self.name}")
        from velora_erp.finance.fulfilment import refresh_for
        refresh_for(self)                                                       # the order or delivery behind this invoice shows Billed %
    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Sales Invoice cannot be deleted.")
