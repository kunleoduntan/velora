from datetime import date, timedelta
from collections import defaultdict
from velora.reporting import Column, ReportBuilder
from velora_erp.hr.report_support import (as_date, period, read, employees, years_between, PAYROLL_ROLES)

def _s(v): return "All" if v in (None, "") else v

RATINGS = ["Exceptional","Exceeds Expectations","Meets Expectations","Partially Meets","Does Not Meet"]

def execute(filters):
    filters = filters or {}
    emps = employees(filters, include_disabled=True)
    cond = {"cycle": filters["cycle"]} if filters.get("cycle") else {}
    revs = [r for r in read("Performance Review", ["name","employee","cycle","review_status","overall_score","overall_rating","calibrated_score"], cond)
            if r["employee"] in emps and r["review_status"] in ("Approved","Acknowledged","Closed")]
    by = defaultdict(list)
    for r in revs: by[emps[r["employee"]]["department"] or "Unassigned"].append(r)
    cols = [Column("department","Department","Link"),Column("n","Reviews","Int")] + [Column("r%d" % i, x, "Int") for i, x in enumerate(RATINGS)] + [Column("avg","Avg Score","Float",total="none"),Column("cal","Avg Calibrated","Float",total="none")]
    rb = ReportBuilder("Performance Rating Distribution", cols)
    def avg(items, k):
        v = [float(i[k]) for i in items if i[k] not in (None, "")]
        return round(sum(v)/len(v), 2) if v else None
    for dept, items in sorted(by.items()):
        row = {"department":dept,"n":len(items),"avg":avg(items,"overall_score"),"cal":avg(items,"calibrated_score")}
        for i, x in enumerate(RATINGS): row["r%d" % i] = sum(1 for r in items if r["overall_rating"] == x)
        rb.row(row)
    rb.total("TOTAL", {"avg":avg(revs,"overall_score"),"cal":avg(revs,"calibrated_score")})
    return rb.build(filters=[("Cycle",_s(filters.get("cycle"))),("Department",_s(filters.get("department")))], notes=["Only approved, acknowledged or closed reviews are counted."])
