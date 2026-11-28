from datetime import datetime
from velora import Document, throw, get_list, get_doc

def _dt(v):
    if not v: return None
    return v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
class Interview(Document):
    def validate(self):
        start,end=_dt(self.scheduled_start),_dt(self.scheduled_end)
        if end and start and end <= start: throw("Interview end must be later than its start.")
        if self.application:
            stage=get_doc("Job Application",self.application,ignore_permissions=True).application_stage
            if stage in ("Rejected","Hired","Withdrawn") and self.interview_status in ("Scheduled",None,""): throw(f"An interview cannot be scheduled for an application that is {stage}.")
        if start and end and self.interviewer and self.interview_status not in ("Cancelled","No Show"):
            for row in get_list("Interview",filters=[["interviewer","=",self.interviewer],["interview_status","not in",["Cancelled","No Show"]]],fields=["name","scheduled_start","scheduled_end"],limit=1000,ignore_permissions=True):
                if row.get("name")==getattr(self,"name",None): continue
                x,y=_dt(row.get("scheduled_start")),_dt(row.get("scheduled_end"))
                if x and y and start<y and end>x: throw(f"The interviewer is already booked in {row.get('name')} at that time.")
        if self.interview_status == "Completed" and not self.recommendation:
            throw("Record an interviewer recommendation before completing the interview.")
