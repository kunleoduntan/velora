"""Approval controls for employee change proposals."""
from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

class EmployeeChangeRequest(Document):
    def validate(self):
        if not self.effective_date: throw("Effective Date is required.")
        if not self.reason: throw("Business Justification is required.")
        if self.request_status in {"Approved","Rejected"}:
            if decided_now(self,"request_status"):
                self.approved_by=get_session().user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        if self.request_status == "Implemented" and not self.implemented_assignment:
            throw("Link the approved Reporting Assignment before marking this request Implemented.")
