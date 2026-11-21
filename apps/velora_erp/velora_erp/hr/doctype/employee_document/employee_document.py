"""Validation and approval controls for employee documents."""
from datetime import date, datetime
from velora import Document, throw
from velora.permissions import get_session

def _date(v):
    if not v: return None
    return v if isinstance(v,date) else date.fromisoformat(str(v)[:10])

class EmployeeDocument(Document):
    def validate(self):
        issue,expiry=_date(self.issue_date),_date(self.expiry_date)
        if issue and expiry and expiry < issue: throw("Expiry Date cannot be earlier than Issue Date.")
        if self.verification_status in {"Verified","Rejected"}:
            s=get_session()
            self.verified_by=s.user
            self.verified_on=datetime.utcnow().replace(microsecond=0)
