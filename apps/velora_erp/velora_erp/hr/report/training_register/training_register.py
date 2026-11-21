from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=365); today = date.today()
    emps = employees(filters)
    cond = {"status": filters["status"]} if filters.get("status") else {}
    sessions = {s["name"]: s for s in read("Training Session", ["name","session_title","start_datetime","program"])}
    rows = [r for r in read("Training Enrollment", ["name","employee","session","status","attendance_status","assessment_score","training_cost","training_completed_on","certificate_expiry_date"], cond) if r["employee"] in emps]
    rb = ReportBuilder("Training Register", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("program","Program","Link"),
        Column("session","Session"),Column("start","Starts","Date"),Column("status","Status"),Column("attendance","Attendance"),Column("score","Score","Float",total="none"),
        Column("cost","Cost","Currency"),Column("expiry","Certificate Expiry","Date"),Column("cert","Certificate")])
    shown = 0
    for r in sorted(rows, key=lambda r:(emps[r["employee"]]["employee_name"] or "", str(r["name"]))):
        s = sessions.get(r["session"]) or {}; st = as_date(s.get("start_datetime")); exp = as_date(r["certificate_expiry_date"])
        if st and not (start <= st <= end): continue
        cert = "Expired" if exp and exp < today else "Expiring in 60 days" if exp and exp <= today + timedelta(days=60) else "Valid" if exp else ""
        if filters.get("expiring_only") and str(filters["expiring_only"]) not in ("0","") and cert not in ("Expired","Expiring in 60 days"): continue
        e = emps[r["employee"]]; shown += 1
        rb.row({"employee":r["employee"],"employee_name":e["employee_name"],"department":e["department"],"program":s.get("program"),"session":s.get("session_title"),"start":st,
                "status":r["status"],"attendance":r["attendance_status"],"score":r["assessment_score"],"cost":r["training_cost"],"expiry":exp,"cert":cert})
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end)], summary=[{"label":"Enrolments","value":shown,"fieldtype":"Int"}])
