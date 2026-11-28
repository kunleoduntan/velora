"""Timesheet validation and payroll hand-off contract."""
from decimal import Decimal, InvalidOperation
from datetime import date

def validate_timesheet(entry):
    required=("employee","project","work_date","hours")
    missing=[k for k in required if not str(entry.get(k) if entry.get(k) is not None else "").strip()]
    if missing: raise ValueError("Timesheet entry requires: "+", ".join(missing))
    try: date.fromisoformat(str(entry["work_date"]))
    except ValueError: raise ValueError("work_date must use ISO YYYY-MM-DD format.")
    try: hours=Decimal(str(entry["hours"]))
    except (InvalidOperation,TypeError,ValueError): raise ValueError("hours must be numeric.")
    if not hours.is_finite() or hours<=0 or hours>24: raise ValueError("Daily timesheet hours must be greater than zero and no more than 24.")
    status=entry.get("status","Draft")
    if status not in {"Draft","Submitted","Approved","Rejected"}: raise ValueError("Unsupported timesheet status.")
    if status=="Approved" and not entry.get("approved_by"): raise ValueError("Approved timesheet requires approved_by.")
    if status=="Approved" and not entry.get("approval_reference"): raise ValueError("Approved timesheet requires an approval reference.")
    return {"valid":True,"hours":hours,"payroll_handoff_permitted":status=="Approved","posting_authority":"Payroll/Accounting","ledger_write_permitted":False}

def aggregate_timesheet_hours(entries):
    totals={}
    for entry in entries:
        result=validate_timesheet(entry)
        if entry.get("status")!="Approved": continue
        key=(entry["employee"],entry["project"],entry["work_date"])
        totals[key]=totals.get(key,Decimal("0"))+result["hours"]
    employee_day = {}
    for (employee, project, work_date), hours in totals.items():
        key = (employee, work_date)
        employee_day[key] = employee_day.get(key, Decimal("0")) + hours
    over = [{"employee":k[0],"work_date":k[1],"hours":v} for k,v in employee_day.items() if v > 24]
    if over: raise ValueError("Approved timesheet total exceeds 24 hours for an employee/date across all projects.")
    return [{"employee":k[0],"project":k[1],"work_date":k[2],"approved_hours":v} for k,v in sorted(totals.items())]
