"""Validation for HR-owned employment contracts."""
from datetime import date
from velora import Document, get_list, throw
from velora.permissions import get_session

def _date(v):
    if not v: return None
    return v if isinstance(v,date) else date.fromisoformat(str(v)[:10])

class EmploymentContract(Document):
    def validate(self):
        start,end,probation=_date(self.start_date),_date(self.end_date),_date(self.probation_end_date)
        if not start: throw("Contract Start Date is required.")
        if end and end < start: throw("Contract End Date cannot be earlier than Start Date.")
        if probation and probation < start: throw("Probation End Date cannot be earlier than Contract Start Date.")
        if self.contract_status == "Approved":
            rows=get_list("Employment Contract",filters={"employee":self.employee,"contract_status":"Approved"},fields=["name","start_date","end_date"],limit=1000,ignore_permissions=True)
            for row in rows:
                if row["name"] == getattr(self,"name",None): continue
                other_start,other_end=_date(row.get("start_date")),_date(row.get("end_date"))
                if other_start and (end is None or other_start <= end) and (other_end is None or other_end >= start):
                    throw(f"Approved contract {row['name']} overlaps this contract period.")
