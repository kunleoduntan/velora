from datetime import date
from velora import Document, throw

def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
class JobPosting(Document):
    def validate(self):
        if _d(self.closing_date) and _d(self.publish_date) and _d(self.closing_date) < _d(self.publish_date):
            throw("Closing Date cannot be earlier than Publish Date.")
        if self.posting_status == "Published" and not self.public_description:
            throw("A public job description is required before publishing.")
