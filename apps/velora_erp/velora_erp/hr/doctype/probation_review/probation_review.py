"""Validation for probation review and confirmation recommendations."""
from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

def _date(v):
    if not v: return None
    return v if isinstance(v,date) else date.fromisoformat(str(v)[:10])

class ProbationReview(Document):
    def validate(self):
        due,review,extension=_date(self.due_date),_date(self.review_date),_date(self.extension_end_date)
        if not due: throw("Review Due Date is required.")
        if review and review < due: throw("Review Date cannot be earlier than Review Due Date.")
        if self.recommendation == "Extend Probation" and not extension:
            throw("An Extended Probation End Date is required when recommending an extension.")
        if self.recommendation == "Confirm" and self.approval_status == "Approved":
            s=get_session()
        if self.approval_status == "Approved":
            s=get_session()
            if decided_now(self,'approval_status'):
                self.approved_by=s.user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)

    def on_update(self):
        """An approved confirmation recommendation confirms the employee (date of confirmation, out of probation)."""
        if self.approval_status != "Approved" or self.recommendation != "Confirm" or not self.employee:
            return
        from velora import get_doc
        from velora_erp.finance.doctype._utils import db_update
        employee = get_doc("Employee", self.employee, ignore_permissions=True)
        values = {}
        if not employee.date_of_confirmation:
            values["date_of_confirmation"] = (_date(self.review_date) or date.today())
        if employee.employment_status == "Probation":
            values["employment_status"] = "Active"
        if values:
            db_update(employee, **values)
