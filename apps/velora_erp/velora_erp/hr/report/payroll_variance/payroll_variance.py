from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

def execute(filters):
    filters = filters or {}
    cf, ct = period({"from_date":filters.get("current_from"),"to_date":filters.get("current_to")}, default_days=30)
    pf, pt = period({"from_date":filters.get("previous_from"),"to_date":filters.get("previous_to")}, default_days=30) if filters.get("previous_to") else (cf - (ct - cf) - timedelta(days=1), cf - timedelta(days=1))
    emps = employees(filters, include_disabled=True)
    slips = [s for s in read("Salary Slip", ["employee","period_start","period_end","gross_earnings","net_pay"], {"docstatus":1}) if s["employee"] in emps]
    def total(a, b, key):
        out = defaultdict(float)
        for s in slips:
            if as_date(s["period_end"]) >= a and as_date(s["period_start"]) <= b: out[s["employee"]] += float(s[key] or 0)
        return out
    cg, pg, cn, pn = total(cf, ct, "gross_earnings"), total(pf, pt, "gross_earnings"), total(cf, ct, "net_pay"), total(pf, pt, "net_pay")
    rb = ReportBuilder("Payroll Variance", [Column("employee","Employee","Link"),Column("employee_name","Name"),Column("department","Department","Link"),Column("prev_gross","Previous Gross","Currency"),
        Column("cur_gross","Current Gross","Currency"),Column("diff","Change","Currency"),Column("pct","Change %","Percent",total="none"),Column("prev_net","Previous Net","Currency"),Column("cur_net","Current Net","Currency"),Column("flag","Flag")])
    for emp in sorted(set(cg) | set(pg), key=lambda x: emps[x]["employee_name"] or ""):
        e = emps[emp]; a, b = pg.get(emp, 0.0), cg.get(emp, 0.0); diff = b - a
        flag = "New in period" if a == 0 else "Not paid this period" if b == 0 else "Change over 10%" if abs(diff)/a > 0.10 else ""
        rb.row({"employee":emp,"employee_name":e["employee_name"],"department":e["department"],"prev_gross":round(a,2),"cur_gross":round(b,2),"diff":round(diff,2),
                "pct":round(diff/a*100,1) if a else None,"prev_net":round(pn.get(emp,0.0),2),"cur_net":round(cn.get(emp,0.0),2),"flag":flag})
    rb.total("TOTAL")
    return rb.build(filters=[("Current",f"{cf} to {ct}"),("Previous",f"{pf} to {pt}")], notes=["When no previous period is given, the period of equal length immediately before the current one is used."])
