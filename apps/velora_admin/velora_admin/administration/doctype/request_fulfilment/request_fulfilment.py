from datetime import datetime
from velora import Document, throw


class RequestFulfilment(Document):
    """Validate the operational fulfilment record for an approved request."""

    def validate(self):
        if not self.request:
            throw("Request is required.")
        if self.progress_percent is not None and not 0 <= float(self.progress_percent) <= 100:
            throw("Progress must be between 0 and 100 percent.")
        if self.status == "Completed":
            if float(self.progress_percent or 0) != 100:
                throw("Completed fulfilment must have 100 percent progress.")
            if not (self.completion_notes or "").strip():
                throw("Completion Notes are required when completing fulfilment.")
            if not self.completed_on:
                self.completed_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.status == "In Progress" and not self.started_on:
            self.started_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
