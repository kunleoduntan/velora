from datetime import date, datetime, timezone
from velora import Document, throw
from velora.permissions import get_session
def _d(v): return v if isinstance(v,date) else date.fromisoformat(str(v)[:10]) if v else None
class PerformanceImprovementPlan(Document):
    def validate(self):
        start,end=_d(self.start_date),_d(self.end_date)
        if not start or not end or end < start: throw("PIP End Date must be on or after Start Date.")
        if self.status in ("Pending Approval","Active","Successfully Completed","Extended","Unsuccessful") and not (self.reason and self.expected_outcomes and self.success_measure): throw("Reason, expected outcomes and success measures are mandatory.")
        if self.status == "Active":
            s=get_session()
            if not self.approved_by: self.approved_by=s.user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
        if self.status == "Successfully Completed" and not self.outcome: throw("Record the evidence-based outcome before completing the PIP.")
