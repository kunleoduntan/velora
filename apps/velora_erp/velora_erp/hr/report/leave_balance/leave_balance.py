from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    as_of = as_date(filters.get("as_of")) or date.today()
    emps = employees(filters)
    cond = {"allocation_status":"Approved"}
    if filters.get("leave_type"): cond["leave_type"] = filters["leave_type"]
    rows = [a for a in read("Leave Allocation", ["name","employee","leave_type","period_start","period_end","allocated_days","carry_forward_days","adjustment_days","used_days","pending_days","available_days"], cond)
            if a["employee"] in emps and as_date(a["period_start"]) <= as_of <= as_date(a["period_end"])]
    rb = ReportBuilder("Leave Balance", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("leave_type","Leave Type","Link"),
        Column("period_end","Period Ends","Date"),Column("allocated_days","Allocated","Float"),Column("carry_forward_days","Carried Forward","Float"),Column("adjustment_days","Adjustments","Float"),
        Column("used_days","Used","Float"),Column("pending_days","Pending","Float"),Column("available_days","Available","Float")])
    for a in sorted(rows, key=lambda r:(emps[r["employee"]]["employee_name"] or "", r["leave_type"])):
        e = emps[a["employee"]]
        rb.row({"employee":a["employee"],"employee_name":e["employee_name"],"department":e["department"],**{k:a[k] for k in ("leave_type","period_end","allocated_days","carry_forward_days","adjustment_days","used_days","pending_days","available_days")}})
    rb.total("TOTAL")
    return rb.build(filters=[("As Of",as_of),("Leave Type",_s(filters.get("leave_type"))),("Department",_s(filters.get("department")))])
