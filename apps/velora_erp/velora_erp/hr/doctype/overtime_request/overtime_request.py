from datetime import datetime, timezone
from velora import Document, throw, get_list, get_doc
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

def _dt(v): return v if isinstance(v,datetime) else (datetime.fromisoformat(str(v).replace("Z","+00:00")) if v else None)
class OvertimeRequest(Document):
    def validate(self):
        old=getattr(self,"_old",None) or {}
        if old and (old.get("payroll_input") or old.get("payroll_review_status") in ("Accepted as Payroll Input","Not Payable")):
            for f in ("employee","overtime_date","start_time","end_time"):
                if str(old.get(f) or "")[:19]!=str(getattr(self,f,None) or "")[:19]:
                    throw(f"This overtime has already been reviewed for payroll and its {f.replace('_',' ')} can no longer change.")
        a,b=_dt(self.start_time),_dt(self.end_time)
        if a and b:
            if b<=a: throw("Overtime end must be later than start.")
            self.hours=round((b-a).total_seconds()/3600,2)
            if self.hours>24: throw("A single overtime request cannot exceed 24 hours.")
            if self.overtime_date and str(self.overtime_date)[:10]!=a.date().isoformat(): throw("Overtime start must fall on the overtime date.")
            if self.employee:
                for row in get_list("Overtime Request",filters=[["employee","=",self.employee],["approval_status","!=","Rejected"]],fields=["name","start_time","end_time"],limit=1000,ignore_permissions=True):
                    if row.get("name")==getattr(self,"name",None): continue
                    x,y=_dt(row.get("start_time")),_dt(row.get("end_time"))
                    if x and y and a<y and b>x: throw(f"This overtime overlaps {row.get('name')} for the same employee.")
        if self.approval_status in {"Approved","Rejected"}:
            s=get_session()
            if decided_now(self,"approval_status"):
                self.approved_by=s.user; self.approved_on=datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)
            if self.approval_status=="Approved" and self.payroll_review_status=="Not Submitted": self.payroll_review_status="Pending Review"
        if self.payroll_input and self.approval_status!="Approved": throw("Only approved overtime can be linked to a Payroll Input.")
