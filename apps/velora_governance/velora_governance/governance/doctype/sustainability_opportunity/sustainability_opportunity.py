from velora import Document, throw

class SustainabilityOpportunity(Document):
    def validate(self):
        if self.financial_impact is not None and float(self.financial_impact)<0:
            throw("Potential Financial Impact cannot be negative.")
