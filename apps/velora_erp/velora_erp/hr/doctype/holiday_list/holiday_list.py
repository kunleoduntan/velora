import json
from datetime import date
from velora import Document, throw
class HolidayList(Document):
    def validate(self):
        rows=self.holiday_dates
        if isinstance(rows,str):
            try: rows=json.loads(rows or "[]")
            except Exception: throw("Holiday dates must be a valid JSON array.")
        if not isinstance(rows,list): throw("Holiday dates must be a JSON array of ISO dates.")
        normal=[]
        for value in rows:
            try: normal.append(date.fromisoformat(str(value)[:10]).isoformat())
            except Exception: throw(f"Invalid holiday date: {value}")
        if len(normal)!=len(set(normal)): throw("Holiday list cannot contain duplicate dates.")
        if self.year and any(date.fromisoformat(x).year!=int(self.year) for x in normal): throw("Every holiday date must belong to the selected calendar year.")
        self.holiday_dates=json.dumps(sorted(normal))
