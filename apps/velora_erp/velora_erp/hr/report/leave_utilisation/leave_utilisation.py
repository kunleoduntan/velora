from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=365)
    emps = employees(filters)
    cond = {}
    if filters.get("leave_type"): cond["leave_type"] = filters["leave_type"]
    apps = [a for a in read("Leave Application", ["employee","leave_type","from_date","to_date","total_days","workflow_status","payroll_treatment"], cond)
            if a["employee"] in emps and a["workflow_status"] in ("Approved","Completed") and as_date(a["to_date"]) >= start and as_date(a["from_date"]) <= end]
    types = sorted({a["leave_type"] for a in apps})
    cols = [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link")] + [Column("t_"+str(i),t,"Float") for i,t in enumerate(types)] + [Column("total","Total Days","Float"),Column("unpaid","Unpaid Days","Float"),Column("episodes","Applications","Int")]
    by = defaultdict(lambda: {"t":defaultdict(float),"unpaid":0.0,"n":0})
    for a in apps:
        d = by[a["employee"]]; days = float(a["total_days"] or 0); d["t"][a["leave_type"]] += days; d["n"] += 1
        if a["payroll_treatment"] == "Unpaid Leave": d["unpaid"] += days
    rb = ReportBuilder("Leave Utilisation", cols)
    for emp, d in sorted(by.items(), key=lambda kv: emps[kv[0]]["employee_name"] or ""):
        e = emps[emp]; row = {"employee":emp,"employee_name":e["employee_name"],"department":e["department"],"total":sum(d["t"].values()),"unpaid":d["unpaid"],"episodes":d["n"]}
        for i,t in enumerate(types): row["t_"+str(i)] = d["t"].get(t, 0)
        rb.row(row)
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end)], notes=["Only Approved and Completed applications overlapping the period are counted; days are not pro-rated at the period edges."])
