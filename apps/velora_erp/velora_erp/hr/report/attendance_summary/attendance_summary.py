from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=30)
    emps = employees(filters)
    recs = [a for a in read("Attendance", ["employee","attendance_date","status","worked_hours","late_minutes","early_exit_minutes","approval_status"], {})
            if a["employee"] in emps and start <= as_date(a["attendance_date"]) <= end and a["approval_status"] in ("Approved", None, "")]
    by = defaultdict(lambda: defaultdict(float))
    for a in recs:
        d = by[a["employee"]]; s = a["status"]
        d["present"] += 1 if s in ("Present","Work From Home","Outdoor Duty") else 0.5 if s == "Half Day" else 0
        d["absent"] += 1 if s == "Absent" else 0; d["leave"] += 1 if s == "On Leave" else 0
        d["half"] += 1 if s == "Half Day" else 0; d["late"] += 1 if (a["late_minutes"] or 0) > 0 else 0
        d["late_min"] += float(a["late_minutes"] or 0); d["hours"] += float(a["worked_hours"] or 0); d["days"] += 1 if s not in ("Holiday","Weekly Off") else 0
    rb = ReportBuilder("Attendance Summary", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("present","Present","Float"),
        Column("half","Half Days","Float"),Column("absent","Absent","Float"),Column("leave","On Leave","Float"),Column("late","Late Days","Int"),Column("late_min","Late Minutes","Int"),
        Column("hours","Hours Worked","Float"),Column("rate","Attendance %","Percent",total="none")])
    for emp, d in sorted(by.items(), key=lambda kv: emps[kv[0]]["employee_name"] or ""):
        e = emps[emp]; working = d["days"] - d["leave"]
        rb.row({"employee":emp,"employee_name":e["employee_name"],"department":e["department"],"present":d["present"],"half":d["half"],"absent":d["absent"],"leave":d["leave"],
                "late":int(d["late"]),"late_min":int(d["late_min"]),"hours":round(d["hours"],2),"rate":round(d["present"]/working*100,1) if working else None})
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end),("Department",_s(filters.get("department")))], notes=["Rate = days present / (working days - approved leave). Holidays and weekly offs are excluded. Unapproved attendance is ignored."])
