from velora import Document, throw

class SustainabilityStandard(Document):
    def validate(self):
        if not self.standard_code or not self.standard_title:
            throw("Standard Code and Standard Title are required.")
