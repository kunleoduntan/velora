from velora import Document, throw

class SustainabilityDisclosure(Document):
    def validate(self):
        if not self.disclosure_code or not self.disclosure_title:
            throw("Disclosure Code and Disclosure Title are required.")
