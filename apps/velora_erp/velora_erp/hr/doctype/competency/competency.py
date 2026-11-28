from velora import Document, throw
class Competency(Document):
    def validate(self):
        if not str(self.competency_code or "").strip(): throw("Competency Code is required.")
        if not str(self.competency_name or "").strip(): throw("Competency Name is required.")
