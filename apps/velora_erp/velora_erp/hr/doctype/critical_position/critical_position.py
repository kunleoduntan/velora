from velora import Document, throw

class CriticalPosition(Document):
    def validate(self):
        if int(self.target_coverage or 0) < 0 or int(self.target_coverage or 0) > 20:
            throw('Target Successor Coverage must be between 0 and 20.')
