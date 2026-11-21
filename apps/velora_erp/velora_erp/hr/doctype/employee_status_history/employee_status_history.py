"""Approval controls for effective-dated employee lifecycle events."""
from datetime import date, datetime
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

class EmployeeStatusHistory(Document):
    def validate(self):
        if not self.effective_date: throw("Effective Date is required.")
        if not self.reason: throw("A reason is required for every employee lifecycle event.")
        if self.approval_status == "Approved":
            if decided_now(self,"approval_status"):
                self.approved_by=get_session().user
                self.approved_on=datetime.utcnow().replace(microsecond=0)
