from velora import Document


class TaxJurisdiction(Document):
    def validate(self):
        self.jurisdiction_code = (self.jurisdiction_code or '').strip().upper()
