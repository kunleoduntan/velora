"""Headcount arithmetic shared by the Department Staff Budget, Job Requisition and the staffing report."""
from __future__ import annotations
from datetime import date, datetime
from velora import get_list

_LEFT = ("Left",)
_OPEN_REQUISITION = ("Pending Approval", "Approved")


def as_date(v):
    if not v: return None
    if isinstance(v, datetime): return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def months_between(start, end) -> int:
    a, b = as_date(start), as_date(end)
    if not a or not b or b < a: return 0
    return max(1, (b.year - a.year) * 12 + (b.month - a.month) + 1)


def filled(department, designation=None) -> int:
    """People employed now (not left, not disabled) in a department, optionally for one designation."""
    flt = [["department", "=", department], ["employment_status", "!=", "Left"], ["disabled", "=", 0]]
    if designation: flt.append(["designation", "=", designation])
    return len(get_list("Employee", filters=flt, fields=["name"], limit=100000, ignore_permissions=True))


def committed(department, designation=None, exclude=None, start=None, end=None) -> int:
    """Open positions on pending/approved requisitions: vacancies requested less those already hired."""
    flt = [["department", "=", department], ["requisition_status", "in", list(_OPEN_REQUISITION)]]
    if designation: flt.append(["designation", "=", designation])
    reqs = get_list("Job Requisition", filters=flt, fields=["name", "vacancy_count", "target_start_date"], limit=100000, ignore_permissions=True)
    s, e, total = as_date(start), as_date(end), 0
    for r in reqs:
        if exclude and r["name"] == exclude: continue
        when = as_date(r.get("target_start_date"))
        if when and ((s and when < s) or (e and when > e)): continue
        hired = len(get_list("Job Application", filters=[["requisition", "=", r["name"]], ["application_stage", "=", "Hired"]], fields=["name"], limit=100000, ignore_permissions=True))
        total += max(0, int(r.get("vacancy_count") or 0) - hired)
    return total


def budget_for(department, designation, on, exclude_budget=None):
    """The approved staff budget line covering this department/designation on a date, or None."""
    day = as_date(on) or date.today()
    for b in get_list("Department Staff Budget", filters=[["department", "=", department], ["budget_status", "=", "Approved"]],
                      fields=["name", "from_date", "to_date"], limit=1000, ignore_permissions=True):
        if exclude_budget and b["name"] == exclude_budget: continue
        if as_date(b["from_date"]) <= day <= as_date(b["to_date"]):
            from velora import get_doc
            doc = get_doc("Department Staff Budget", b["name"], ignore_permissions=True)
            for ln in doc.lines or []:
                if (ln.get("designation") if isinstance(ln, dict) else ln.designation) == designation:
                    return doc, ln
    return None, None
