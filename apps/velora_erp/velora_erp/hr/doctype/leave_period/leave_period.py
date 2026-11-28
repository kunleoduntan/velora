from datetime import date
from velora import Document, get_list, throw
from velora.permissions import get_session

def _date(v):
    return v if isinstance(v,date) else (date.fromisoformat(str(v)[:10]) if v else None)

class LeavePeriod(Document):
    def validate(self):
        start,end=_date(self.from_date),_date(self.to_date)
        if not self.period_code or not self.period_name or not start or not end or end<start:
            throw("Period Code, Period Name and a valid date range are required.")
        if self.period_status in {"Open","Closed"}:
            pass
        rows=get_list("Leave Period",fields=["name","from_date","to_date"],limit=1000,ignore_permissions=True)
        for row in rows:
            if row.get("name")==getattr(self,"name",None): continue
            a,b=_date(row.get("from_date")),_date(row.get("to_date"))
            if a and b and start<=b and end>=a:
                throw("Leave Period dates cannot overlap another Leave Period.")
