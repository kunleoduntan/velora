from velora import Document, get_doc, throw


class RequestForQuotation(Document):
    def validate(self):
        if self.quote_by and self.transaction_date and self.quote_by < self.transaction_date:
            throw("Quotations Wanted By cannot be before the request date.")
        seen = set()
        for index, row in enumerate(self.items or [], 1):
            if float(row.quantity or 0) <= 0:
                throw(f"Item row {index}: quantity must be greater than zero.")
            if row.item_code in seen:
                throw(f"Item row {index}: {row.item_code} is listed twice.")
            seen.add(row.item_code)
        asked = set()
        for index, row in enumerate(self.suppliers or [], 1):
            if row.supplier in asked:
                throw(f"Supplier row {index}: {row.supplier} is listed twice.")
            asked.add(row.supplier)
            if get_doc("Supplier", row.supplier).disabled:
                throw(f"Supplier row {index}: {row.supplier} is disabled.")
        old = (getattr(self, "_old", None) or {}).get("status")
        if self.status != old and self.status in ("Quotations Received", "Awarded") and old is not None:
            throw(f"The status moves to {self.status} by itself when a quotation is received or ordered from.")
        if self.status == "Cancelled" and old != "Cancelled" and self.awarded_quotation:
            throw("A request that has been ordered from cannot be cancelled.")
        if self.status in ("Quotations Received", "Awarded") and old is None:
            self.status = "Draft"
