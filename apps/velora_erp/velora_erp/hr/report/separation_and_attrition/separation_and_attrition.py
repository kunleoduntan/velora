from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=365)
    emps = employees(filters, include_disabled=True)
    cond = {"separation_type": filters["separation_type"]} if filters.get("separation_type") else {}
    rows = [s for s in read("Employee Separation", ["name","employee","separation_type","notice_date","last_working_date","reason","eligible_for_rehire","workflow_status","clearance_completed","final_settlement_status"], cond)
            if s["employee"] in emps and s["workflow_status"] not in ("Draft","Rejected","Cancelled") and s["last_working_date"] and start <= as_date(s["last_working_date"]) <= end]
    rb = ReportBuilder("Separation and Attrition", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("designation","Designation","Link"),
        Column("type","Type"),Column("notice","Notice Date","Date"),Column("last_day","Last Working Date","Date"),Column("tenure","Tenure (Years)","Float",total="none"),
        Column("rehire","Eligible for Rehire","Check"),Column("status","Status"),Column("settlement","Final Settlement"),Column("reason","Reason")])
    for s in sorted(rows, key=lambda s: str(s["last_working_date"])):
        e = emps[s["employee"]]
        rb.row({"employee":s["employee"],"employee_name":e["employee_name"],"department":e["department"],"designation":e["designation"],"type":s["separation_type"],"notice":s["notice_date"],
                "last_day":s["last_working_date"],"tenure":years_between(e["date_of_joining"],s["last_working_date"]),"rehire":s["eligible_for_rehire"],"status":s["workflow_status"],
                "settlement":s["final_settlement_status"],"reason":s["reason"]})
    rb.total("TOTAL")
    by_type = defaultdict(int)
    for s in rows: by_type[s["separation_type"]] += 1
    return rb.build(filters=[("From",start),("To",end)], summary=[{"label":"Leavers","value":len(rows),"fieldtype":"Int"}]+[{"label":k,"value":v,"fieldtype":"Int"} for k,v in sorted(by_type.items())])
