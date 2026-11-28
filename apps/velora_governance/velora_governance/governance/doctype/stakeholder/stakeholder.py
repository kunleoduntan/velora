from velora import Document, throw

class Stakeholder(Document):
    def validate(self):
        if self.stakeholder_status=="Active" and not self.stakeholder_name:
            throw("Active Stakeholders require a name.")
