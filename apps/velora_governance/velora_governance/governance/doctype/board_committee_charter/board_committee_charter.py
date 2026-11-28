from velora import Document, throw

class BoardCommitteeCharter(Document):
    def validate(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            throw("Charter Effective To cannot be earlier than Effective From.")
        if self.charter_status == "Active" and not self.document_reference:
            throw("An active Committee Charter must have a document reference.")
