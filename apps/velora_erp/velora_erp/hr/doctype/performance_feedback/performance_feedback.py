from datetime import datetime
from velora import Document, throw
class PerformanceFeedback(Document):
    def validate(self):
        if self.is_anonymous and self.provider: throw("Anonymous feedback must not identify a Feedback Provider.")
        if self.is_anonymous and self.confidentiality == "Share with Employee": throw("Anonymous feedback cannot be shared directly with the employee unless explicitly de-identified by HR.")
        if self.status == "Submitted" and not (self.strengths or self.development_opportunities or self.examples): throw("Provide substantive feedback before submitting.")
        if self.status == "Submitted" and not self.submitted_on: self.submitted_on=datetime.utcnow().replace(microsecond=0)
