from velora import Document, throw

class SustainabilityRisk(Document):
    def validate(self):
        if not 1<=int(self.likelihood or 0)<=5 or not 1<=int(self.impact or 0)<=5:
            throw("Sustainability Risk Likelihood and Impact must be between 1 and 5.")
        self.risk_score=int(self.likelihood)*int(self.impact)
