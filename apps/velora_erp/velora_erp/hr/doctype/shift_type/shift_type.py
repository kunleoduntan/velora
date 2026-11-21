from datetime import datetime
from velora import Document, throw

def _minutes(v):
    try: h,m=map(int,str(v).split(":")); return h*60+m
    except Exception: throw("Shift times must use HH:MM format.")
class ShiftType(Document):
    def validate(self):
        a,b=_minutes(self.start_time),_minutes(self.end_time)
        if not 0<=a<1440 or not 0<=b<1440: throw("Shift times must be between 00:00 and 23:59.")
        if a==b and not self.crosses_midnight: throw("Start and end time cannot be identical unless the shift spans 24 hours.")
        gross=(b-a) if b>a else (1440-a+b)
        if b<a and not self.crosses_midnight: throw("End time is earlier than start time; mark this as a night shift if intended.")
        if int(self.break_minutes or 0)<0 or int(self.break_minutes or 0)>=gross: throw("Break minutes must be non-negative and shorter than the shift.")
        computed=round((gross-int(self.break_minutes or 0))/60,2)
        if self.expected_hours and abs(float(self.expected_hours)-computed)>0.02: throw("Expected working hours do not match shift duration less unpaid break.")
        self.expected_hours=computed
