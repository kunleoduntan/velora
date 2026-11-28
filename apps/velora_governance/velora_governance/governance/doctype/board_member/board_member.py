from velora import Document, throw

class BoardMember(Document):
    def validate(self):
        parts = [self.first_name, self.middle_name, self.last_name]
        composed = " ".join(str(p).strip() for p in parts if p and str(p).strip())
        if composed:
            self.full_name = composed
        elif not self.full_name or not str(self.full_name).strip():
            throw("Full Name or at least one name component is required.")
