from datetime import date
from velora import Document, throw
class TrainingProgram(Document):
    def validate(self):
        if self.start_date and self.end_date and date.fromisoformat(str(self.end_date)[:10]) < date.fromisoformat(str(self.start_date)[:10]): throw("End Date cannot precede Start Date.")
        if self.budget_amount is not None and float(self.budget_amount) < 0: throw("Budget Amount cannot be negative.")

