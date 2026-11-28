from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=90)
    emps = employees(filters)
    cond = {"approval_status": filters["approval_status"]} if filters.get("approval_status") else {}
    rows = [r for r in read("Overtime Request", ["name","employee","overtime_date","overtime_type","hours","approval_status","payroll_review_status","payroll_input"], cond)
            if r["employee"] in emps and start <= as_date(r["overtime_date"]) <= end]
    rb = ReportBuilder("Overtime Register", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("overtime_date","Date","Date"),
        Column("overtime_type","Type"),Column("hours","Hours","Float"),Column("approval_status","Approval"),Column("payroll_review_status","Payroll Review"),Column("payroll_input","Payroll Input","Link")])
    for r in sorted(rows, key=lambda r:(emps[r["employee"]]["employee_name"] or "", str(r["overtime_date"]))):
        e = emps[r["employee"]]
        rb.row({"employee":r["employee"],"employee_name":e["employee_name"],"department":e["department"],**{k:r[k] for k in ("overtime_date","overtime_type","hours","approval_status","payroll_review_status","payroll_input")}})
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end),("Status",_s(filters.get("approval_status")))])
