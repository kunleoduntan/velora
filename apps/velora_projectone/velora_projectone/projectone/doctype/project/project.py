"""Controller for Project: the single Project record used by ProjectOne and by every accounting document."""
from velora import Document, throw


class Project(Document):
    def before_insert(self):
        self.project_code = (self.project_code or "").strip().upper()      # the code is the record's name, so it is tidied before naming

    def validate(self):
        self.project_code = (self.project_code or "").strip().upper()
        self.title = (self.title or "").strip()
        if not self.project_code or not self.title:
            throw("Project Code and Title are required.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            throw("The end date cannot be earlier than the start date.")
        if self.actual_start_date and self.actual_end_date and self.actual_end_date < self.actual_start_date:
            throw("The actual end date cannot be earlier than the actual start date.")
        if not 0 <= float(self.progress_percent or 0) <= 100:
            throw("Progress must be between 0 and 100.")
        if (self.approved_budget or 0) < 0:
            throw("The approved budget cannot be negative.")
