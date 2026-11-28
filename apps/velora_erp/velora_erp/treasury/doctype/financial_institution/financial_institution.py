from velora import Document, throw


class FinancialInstitution(Document):
    def validate(self):
        self.institution_name = (self.institution_name or "").strip()
        if not self.institution_name:
            throw("Enter the lender's name.")
