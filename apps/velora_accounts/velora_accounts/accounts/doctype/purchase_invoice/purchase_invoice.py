from ....invoices import InvoiceDocument


class PurchaseInvoice(InvoiceDocument):
    SIDE = "purchase"
