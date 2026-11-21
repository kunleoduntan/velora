from datetime import datetime, date
from velora import Document, throw, get_list, get_doc
from velora.permissions import get_session
from velora_erp.hr.common import decided_now

def _dt(v):
    if isinstance(v,datetime): return v
    if not v: return None
    return datetime.fromisoformat(str(v).replace("Z","+00:00"))
class Attendance(Document):
    def validate(self):
        start,end=_dt(self.check_in),_dt(self.check_out)
        if start and end:
            if end < start: throw("Check-out cannot be earlier than check-in.")
            self.worked_hours=round((end-start).total_seconds()/3600,2)
        elif start or end: throw("Both check-in and check-out are required to calculate worked hours.")
        if self.status in {"Absent","On Leave","Holiday","Weekly Off"} and (start or end): throw("This attendance status cannot have clock-in/out times.")
        if self.employee and self.attendance_date:
            rows=get_list("Attendance",filters=[["employee","=",self.employee],["attendance_date","=",self.attendance_date]],fields=["name"],limit=100,ignore_permissions=True)
            if any(row.get("name")!=getattr(self,"name",None) for row in rows): throw("Only one attendance record is allowed per employee per date.")
        day=_dt(str(self.attendance_date)[:10]) if self.attendance_date else None
        if day and day.date()>date.today(): throw("Attendance cannot be recorded for a future date.")
        if start and day and start.date()!=day.date() and (day.date()-start.date()).days not in (0,1): throw("Check-in must fall on the attendance date.")
        if self.employee and day and self.status in {"Present","Half Day","Work From Home"}:
            leave=get_list("Leave Application",filters=[["employee","=",self.employee],["workflow_status","in",["Approved","Completed"]],["from_date","<=",day.date().isoformat()],["to_date",">=",day.date().isoformat()]],fields=["name","half_day"],limit=5,ignore_permissions=True)
            if any(not x.get("half_day") for x in leave) and self.status!="Half Day": throw("This employee is on approved leave on that date; mark the attendance On Leave instead.")
        if self.approval_status in {"Approved","Rejected"}:
            s=get_session()
            if decided_now(self,"approval_status"):
                self.approved_by=s.user; self.approved_on=datetime.utcnow().replace(microsecond=0)
