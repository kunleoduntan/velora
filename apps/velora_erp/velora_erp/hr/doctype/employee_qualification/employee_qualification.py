"""Validation and verification controls for employee qualifications."""
from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session

class EmployeeQualification(Document):
    def validate(self):
        if self.date_awarded and self.expiry_date:
            a=self.date_awarded if isinstance(self.date_awarded,date) else date.fromisoformat(str(self.date_awarded)[:10])
            b=self.expiry_date if isinstance(self.expiry_date,date) else date.fromisoformat(str(self.expiry_date)[:10])
            if b < a: throw("Qualification Expiry Date cannot be earlier than Date Awarded.")
        if self.verification_status in {"Verified","Rejected"}:
            s=get_session()
            self.verified_by=s.user
            self.verified_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
