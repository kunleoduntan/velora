from datetime import date
from velora import Document, throw

class CareerDevelopmentPlan(Document):
    def validate(self):
        if self.start_date and self.target_date and date.fromisoformat(str(self.target_date)[:10]) < date.fromisoformat(str(self.start_date)[:10]):
            throw('Target Date cannot precede Start Date.')
        if self.status == 'Approved' and not self.employee:
            throw('An approved Career Development Plan must have an employee.')
