from velora import Document, throw

class Shareholder(Document):
    def validate(self):
        if self.shareholder_type=="Organization" and not self.registration_or_identification:
            throw("Organization Shareholders require a Registration/Identification Number.")
