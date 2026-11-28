from velora import Document, throw

class SustainabilityFramework(Document):
    def validate(self):
        if not self.framework_code:
            throw("Framework Code is required.")
