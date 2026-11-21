from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    emps = employees(filters, include_disabled=bool(int(filters.get("include_disabled") or 0)))
    today = date.today()
    rb = ReportBuilder("Employee Directory", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),
        Column("designation","Designation","Link"),Column("branch","Branch","Link"),Column("grade","Grade"),Column("employee_type","Type"),
        Column("date_of_joining","Date Joined","Date"),Column("tenure","Tenure (Years)","Float",total="none"),Column("email","Email"),Column("phone","Phone")])
    for e in emps.values():
        rb.row({"employee":e["name"],"employee_name":e["employee_name"],"department":e["department"],"designation":e["designation"],"branch":e["branch"],
                "grade":e["grade"],"employee_type":e["employee_type"],"date_of_joining":e["date_of_joining"],"tenure":years_between(e["date_of_joining"],today),
                "email":e["email"],"phone":e["phone"]})
    rb.total("TOTAL")
    return rb.build(filters=[("Department",_s(filters.get("department"))),("Branch",_s(filters.get("branch")))],
                    summary=[{"label":"Employees","value":len(emps),"fieldtype":"Int"}])
