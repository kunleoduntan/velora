from datetime import datetime, date
from velora import Document, throw, get_list
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

def _d(v): return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)
class ShiftAssignment(Document):
    def validate(self):
        a,b=_d(self.effective_from),_d(self.effective_to)
        if a and b and b<a: throw("Shift assignment end date cannot precede its start date.")
        try: days=self.days_of_week if isinstance(self.days_of_week,list) else __import__("json").loads(self.days_of_week or "[]")
        except Exception: throw("Days of week must be a valid JSON array.")
        valid={"Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"}
        if not set(days).issubset(valid): throw("Shift assignment contains an invalid weekday.")
        if self.assignment_status=="Approved" and self.employee:
            rows=get_list("Shift Assignment",filters=[["employee","=",self.employee],["assignment_status","=","Approved"]],fields=["name","effective_from","effective_to"],limit=1000,ignore_permissions=True)
            for row in rows:
                if row.get("name")==getattr(self,"name",None): continue
                old_start,old_end=_d(row.get("effective_from")),_d(row.get("effective_to"))
                new_end=b or date.max; old_end=old_end or date.max
                if a and old_start and a<=old_end and old_start<=new_end: throw("Approved shift assignments for one employee cannot overlap.")
        if self.assignment_status=="Approved":
            if decided_now(self,"assignment_status"):
                self.approved_by=get_session().user; self.approved_on=datetime.utcnow().replace(microsecond=0)
