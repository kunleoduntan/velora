from datetime import date
from velora import Document, throw
def _d(v): return v if isinstance(v,date) else date.fromisoformat(str(v)[:10]) if v else None
class PerformanceCycle(Document):
    def validate(self):
        start,end=_d(self.start_date),_d(self.end_date)
        if not start or not end or end < start: throw("Performance Cycle End Date must be on or after Start Date.")
        for field,label in (("goal_setting_deadline","Goal Setting Deadline"),("self_review_deadline","Self Review Deadline"),("manager_review_deadline","Manager Review Deadline")):
            v=_d(getattr(self,field,None))
            if v and (v < start or v > end): throw(f"{label} must fall within the cycle dates.")
        if self.status in ("Active","Review","Calibration","Completed") and not self.review_template:
            throw("Select a Review Template before activating the cycle.")
        if self.review_template:
            from velora import get_doc
            template=get_doc("Performance Review Template",self.review_template,ignore_permissions=True)
            if self.status in ("Active","Review","Calibration","Completed") and not template.active:
                throw("Only an active Review Template can be used by an active Performance Cycle.")
