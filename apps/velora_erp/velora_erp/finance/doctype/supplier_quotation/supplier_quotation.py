from decimal import Decimal

from velora import Document, get_doc, throw


class SupplierQuotation(Document):
    def validate(self):
        rfq = get_doc("Request for Quotation", self.request_for_quotation, ignore_permissions=True)
        if get_doc("Supplier", self.supplier).disabled:
            throw(f"Supplier {self.supplier} is disabled.")
        if self.valid_till and self.quotation_date and self.valid_till < self.quotation_date:
            throw("Valid Until cannot be before the quotation date.")
        if not self.currency or len(str(self.currency)) != 3:
            throw("Currency must be a three-letter ISO code.")
        if float(self.exchange_rate or 0) <= 0:
            throw("Exchange Rate must be greater than zero.")
        old = (getattr(self, "_old", None) or {}).get("status")
        if self.status in ("Awarded", "Lost", "Expired") and self.status != old:
            throw(f"The status becomes {self.status} by itself (when you order, when another quotation is chosen, or when the validity passes).")
        if old in ("Awarded", "Lost", "Expired") and self.status != old:
            throw(f"A quotation that is {old.lower()} cannot be changed.")
        if self.status == "Draft" or old == "Draft" or old is None:
            if rfq.status in ("Awarded", "Cancelled"):
                throw(f"Request for Quotation {rfq.name} is {rfq.status.lower()}; it takes no more quotations.")
        wanted = {str(i.name): i for i in rfq.items}
        total, seen = Decimal("0"), set()
        for index, ln in enumerate(self.lines or [], 1):
            src = wanted.get(str(ln.rfq_line))
            if src is None:                                          # typed in rather than created from the request: match on the item
                src = next((i for i in rfq.items if i.item_code == ln.item_code), None)
                if src is None:
                    throw(f"Line {index}: {ln.item_code} is not on Request for Quotation {rfq.name}.")
                ln.rfq_line = str(src.name)
            if ln.item_code != src.item_code:
                throw(f"Line {index}: the item cannot differ from the request line.")
            if ln.item_code in seen:
                throw(f"Line {index}: {ln.item_code} is quoted twice.")
            seen.add(ln.item_code)
            if float(ln.quantity or 0) <= 0:
                throw(f"Line {index}: quantity must be greater than zero.")
            if float(ln.rate or 0) < 0:
                throw(f"Line {index}: the quoted rate cannot be negative.")
            if self.status != "Draft" and float(ln.rate or 0) <= 0:
                throw(f"Line {index}: enter the rate {self.supplier} quoted for {ln.item_code} before marking the quotation Received.")
            ln.amount = Decimal(str(ln.quantity)) * Decimal(str(ln.rate or 0))
            total += ln.amount
        self.total_amount = total

    def on_update(self):
        from velora_erp.finance.inventory.procurement import after_quotation_saved
        after_quotation_saved(self)

    def before_delete(self):
        if self.status == "Awarded":
            throw("An awarded quotation has been ordered from and cannot be deleted.")
