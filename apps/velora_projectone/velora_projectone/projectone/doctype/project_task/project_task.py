"""Controller for Project Task."""
from velora import Document, throw


class ProjectTask(Document):
    def validate(self):
        if self.planned_start and self.planned_finish and self.planned_finish < self.planned_start:
            throw("The planned finish cannot be earlier than the planned start.")
