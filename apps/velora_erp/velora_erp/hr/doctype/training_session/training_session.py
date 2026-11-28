from datetime import datetime
from velora import Document, throw
class TrainingSession(Document):
    def validate(self):
        if self.start_datetime and self.end_datetime and str(self.end_datetime) <= str(self.start_datetime): throw("Session End must be after Session Start.")
        if self.capacity is not None and int(self.capacity) < 1: throw("Capacity must be at least one.")

