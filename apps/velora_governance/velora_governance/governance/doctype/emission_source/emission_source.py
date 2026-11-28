from velora import Document, throw

class EmissionSource(Document):
    def validate(self):
        if self.scope not in ("Scope 1","Scope 2","Scope 3"):
            throw("Emission Source Scope must be Scope 1, Scope 2 or Scope 3.")
