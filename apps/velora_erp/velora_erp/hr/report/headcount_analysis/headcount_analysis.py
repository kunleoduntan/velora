from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

KEY = {"Department":"department","Designation":"designation","Branch":"branch","Grade":"grade","Employee Type":"employee_type"}

def execute(filters):
    filters = filters or {}
    group = filters.get("group_by") or "Department"; key = KEY.get(group, "department")
    start, end = period(filters)
    emps = employees(filters, include_disabled=True)
    seps = {s["employee"]: s for s in read("Employee Separation", ["employee","last_working_date","workflow_status","separation_type"]) if s["workflow_status"] in ("Approved","Clearance In Progress","Cleared","Closed")}
    data = defaultdict(lambda: {"opening":0,"joiners":0,"leavers":0,"closing":0})
    for e in emps.values():
        g = e.get(key) or "Unassigned"; joined = as_date(e["date_of_joining"]); left = as_date((seps.get(e["name"]) or {}).get("last_working_date"))
        if joined and joined < start and (not left or left >= start): data[g]["opening"] += 1
        if joined and start <= joined <= end: data[g]["joiners"] += 1
        if left and start <= left <= end: data[g]["leavers"] += 1
        if (not joined or joined <= end) and (not left or left > end): data[g]["closing"] += 1
    rb = ReportBuilder("Headcount Analysis", [Column(key,group),Column("opening","Opening","Int"),Column("joiners","Joiners","Int"),Column("leavers","Leavers","Int"),
        Column("closing","Closing","Int"),Column("turnover","Turnover %","Percent",total="none")])
    for g in sorted(data):
        d = data[g]; avg = (d["opening"] + d["closing"]) / 2
        rb.row({key:g,**d,"turnover":round(d["leavers"]/avg*100,1) if avg else None})
    tot = {k: sum(v[k] for v in data.values()) for k in ("opening","joiners","leavers","closing")}; avg = (tot["opening"]+tot["closing"])/2
    rb.total("TOTAL", {"turnover": round(tot["leavers"]/avg*100,1) if avg else None})
    return rb.build(filters=[("Group By",group),("From",start),("To",end)], summary=[{"label":"Closing headcount","value":tot["closing"],"fieldtype":"Int"},
        {"label":"Turnover %","value":round(tot["leavers"]/avg*100,1) if avg else 0,"fieldtype":"Percent"}],
        notes=["Leavers are employees with an approved separation whose last working date falls in the period. Turnover = leavers / average of opening and closing headcount."])
