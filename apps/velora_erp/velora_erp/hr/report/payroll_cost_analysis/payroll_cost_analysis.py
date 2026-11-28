from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    group = filters.get("group_by") or "Department"; start, end = period(filters, default_days=30)
    emps = employees(filters, include_disabled=True)
    slips = [s for s in read("Salary Slip", ["name","employee","department","branch","cost_centre","period_start","period_end","gross_earnings","employee_deductions","loan_repayments","advance_recoveries","employer_contributions","net_pay","total_employer_cost"], {"docstatus":1})
             if s["employee"] in emps and as_date(s["period_end"]) >= start and as_date(s["period_start"]) <= end]
    key = {"Department":"department","Branch":"branch","Cost Centre":"default_cost_centre","Employee":"employee_name"}[group]
    by = defaultdict(lambda: defaultdict(float)); heads = defaultdict(set)
    for s in slips:
        snap = {"department":s.get("department"),"branch":s.get("branch"),"default_cost_centre":s.get("cost_centre")}.get(key)
        g = snap or emps[s["employee"]].get(key) or "Unassigned"; d = by[g]; heads[g].add(s["employee"])
        for k in ("gross_earnings","employee_deductions","loan_repayments","advance_recoveries","employer_contributions","net_pay","total_employer_cost"): d[k] += float(s[k] or 0)
    rb = ReportBuilder("Payroll Cost Analysis", [Column("group",group),Column("heads","Employees","Int",total="none"),Column("gross_earnings","Gross Earnings","Currency"),Column("employee_deductions","Statutory Deductions","Currency"),
        Column("loan_repayments","Loan Repayments","Currency"),Column("advance_recoveries","Advance Recoveries","Currency"),Column("net_pay","Net Pay","Currency"),
        Column("employer_contributions","Employer Contributions","Currency"),Column("total_employer_cost","Total Employer Cost","Currency"),Column("share","% of Cost","Percent",total="none")])
    total = sum(d["total_employer_cost"] for d in by.values())
    for g, d in sorted(by.items(), key=lambda kv: -kv[1]["total_employer_cost"]):
        rb.row({"group":g,"heads":len(heads[g]),**{k:round(v,2) for k,v in d.items()},"share":round(d["total_employer_cost"]/total*100,1) if total else None})
    rb.total("TOTAL", {"heads":len({e for h in heads.values() for e in h})})
    return rb.build(filters=[("Group By",group),("From",start),("To",end)], summary=[{"label":"Total employer cost","value":round(total,2),"fieldtype":"Currency"}], notes=["Posted salary slips only. Department, branch and cost centre are the values recorded on each slip when it was generated, so later transfers do not rewrite history."])
