from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

STAGES = ["Applied","Screening","Shortlisted","Assessment","Interview","Reference Check","Offer","Hired","Rejected","Withdrawn"]

def execute(filters):
    filters = filters or {}
    start, end = period(filters, default_days=180)
    cond = {"requisition": filters["requisition"]} if filters.get("requisition") else {}
    reqs = {r["name"]: r for r in read("Job Requisition", ["name","requisition_title","department","vacancy_count","requisition_status"])}
    apps = [a for a in read("Job Application", ["name","requisition","application_date","application_stage","final_decision_date"], cond)
            if start <= as_date(a["application_date"]) <= end and (not filters.get("department") or (reqs.get(a["requisition"]) or {}).get("department") == filters["department"])]
    by = defaultdict(list)
    for a in apps: by[a["requisition"] or "No requisition"].append(a)
    cols = [Column("requisition","Requisition","Link"),Column("title","Title"),Column("department","Department","Link"),Column("vacancies","Vacancies","Int"),Column("total","Applications","Int")]
    cols += [Column("s%d" % i, s, "Int") for i, s in enumerate(STAGES)] + [Column("days","Avg Days to Decision","Float",total="none")]
    rb = ReportBuilder("Recruitment Pipeline", cols)
    for req, items in sorted(by.items()):
        r = reqs.get(req) or {}; row = {"requisition":req if r else None,"title":r.get("requisition_title") or req,"department":r.get("department"),"vacancies":r.get("vacancy_count"),"total":len(items)}
        for i, s in enumerate(STAGES): row["s%d" % i] = sum(1 for a in items if a["application_stage"] == s)
        done = [(as_date(a["final_decision_date"]) - as_date(a["application_date"])).days for a in items if a["final_decision_date"]]
        row["days"] = round(sum(done)/len(done), 1) if done else None
        rb.row(row)
    rb.total("TOTAL")
    return rb.build(filters=[("From",start),("To",end)], summary=[{"label":"Applications","value":len(apps),"fieldtype":"Int"},{"label":"Hired","value":sum(1 for a in apps if a["application_stage"]=="Hired"),"fieldtype":"Int"}])
