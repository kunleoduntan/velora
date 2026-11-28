from datetime import datetime
from velora import Document, throw


class RequestFulfilmentTask(Document):
    def validate(self):
        if not (self.task_title or "").strip():
            throw("Task title is required.")
        if self.status == "Completed" and not self.completed_on:
            self.completed_on = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.status == "Completed" and not (self.completion_note or "").strip():
            throw("A completion note is required when completing a task.")
