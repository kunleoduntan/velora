from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    horizon = int(filters.get("within_days") or 90); today = date.today(); limit = today + timedelta(days=horizon)
    emps = employees(filters)
    rows = []
    for c in read("Employment Contract", ["name","employee","contract_type","start_date","end_date","probation_end_date","contract_status"]):
        if c["employee"] not in emps or c["contract_status"] not in ("Approved","Expired"): continue
        for kind, field in (("Contract End","end_date"),("Probation End","probation_end_date")):
            d = as_date(c[field])
            if d and d <= limit and (kind == "Contract End" or c["contract_status"] == "Approved"):
                rows.append((d, c, kind))
    rb = ReportBuilder("Contract and Probation Watch", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("contract","Contract","Link"),
        Column("contract_type","Type"),Column("kind","Milestone"),Column("due","Due Date","Date"),Column("days","Days Left","Int",total="none"),Column("flag","Status")])
    for d, c, kind in sorted(rows, key=lambda x: x[0]):
        e = emps[c["employee"]]; left = (d - today).days
        rb.row({"employee":c["employee"],"employee_name":e["employee_name"],"department":e["department"],"contract":c["name"],"contract_type":c["contract_type"],"kind":kind,"due":d,
                "days":left,"flag":"Overdue" if left < 0 else "Due within 30 days" if left <= 30 else "Upcoming"})
    rb.total("TOTAL")
    return rb.build(filters=[("Within Days",horizon)], summary=[{"label":"Overdue","value":sum(1 for d,_,_ in rows if d < today),"fieldtype":"Int"},{"label":"Items listed","value":len(rows),"fieldtype":"Int"}])
