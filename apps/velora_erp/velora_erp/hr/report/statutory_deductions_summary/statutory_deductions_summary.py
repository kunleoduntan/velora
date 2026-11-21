from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=30)
    emps = employees(filters, include_disabled=True)
    slips = {s["name"]: s for s in read("Salary Slip", ["name","employee","period_start","period_end"], {"docstatus":1})
             if s["employee"] in emps and as_date(s["period_end"]) >= start and as_date(s["period_start"]) <= end}
    lines = [l for l in read("Salary Slip Line", ["parent","component_code","component_name","component_type","amount"]) if l["parent"] in slips and l["component_type"] in ("Deduction","Employer Contribution","Loan Repayment","Advance Recovery")]
    if filters.get("component_type"): lines = [l for l in lines if l["component_type"] == filters["component_type"]]
    by = defaultdict(lambda: {"amount":0.0,"emps":set(),"n":0})
    for l in lines:
        k = (l["component_type"], l["component_code"], l["component_name"]); d = by[k]; d["amount"] += float(l["amount"] or 0); d["emps"].add(slips[l["parent"]]["employee"]); d["n"] += 1
    rb = ReportBuilder("Statutory Deductions Summary", [Column("type","Component Type"),Column("code","Code"),Column("name","Component"),Column("heads","Employees","Int",total="none"),Column("slips","Slip Lines","Int"),Column("amount","Amount","Currency")])
    current = None
    for (t, c, n), d in sorted(by.items()):
        if t != current:
            if current is not None: rb.subtotal(current)
            rb.section(t); current = t
        rb.row({"type":t,"code":c,"name":n,"heads":len(d["emps"]),"slips":d["n"],"amount":round(d["amount"],2)})
    if current is not None: rb.subtotal(current)
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end)], notes=["Amounts are taken from posted salary slip lines; remit employer contributions and employee deductions to the relevant agency per its due date."])
