from velora import Document, throw


class PortalAccount(Document):
    def validate(self):
        self.email = (self.email or "").strip().lower()
        if self.portal_type == "Customer":
            if not self.customer:
                throw("Select the customer this portal account belongs to.")
            self.supplier = None
        elif self.portal_type == "Supplier":
            if not self.supplier:
                throw("Select the supplier this portal account belongs to.")
            self.customer = None
