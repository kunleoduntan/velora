from velora import Document, throw

class Board(Document):
    def validate(self):
        if self.minimum_members and self.maximum_members and int(self.minimum_members) > int(self.maximum_members):
            throw("Minimum Members cannot exceed Maximum Members.")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            throw("Effective To cannot be earlier than Effective From.")
