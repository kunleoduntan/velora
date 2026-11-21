from datetime import date
from velora.reporting import Column, ReportBuilder
from velora_erp.hr import staffing
from velora_erp.hr.report_support import as_date, read


def execute(filters):
    filters = filters or {}
    day = as_date(filters.get("as_of")) or date.today()
    cond = {"budget_status": "Approved"}
    if filters.get("department"): cond["department"] = filters["department"]
    rb = ReportBuilder("Staff Budget vs Actual", [
        Column("department", "Department", "Link"), Column("budget", "Budget", "Link"), Column("designation", "Designation", "Link"),
        Column("budgeted", "Budgeted", "Int"), Column("filled", "Employed", "Int"), Column("committed", "Requested", "Int"),
        Column("vacant", "Vacant", "Int"), Column("over", "Over Budget By", "Int"), Column("annual_cost", "Budgeted Cost", "Currency")])
    from velora import get_doc
    for b in read("Department Staff Budget", ["name", "department", "from_date", "to_date"], cond):
        if not (as_date(b["from_date"]) <= day <= as_date(b["to_date"])): continue
        doc = get_doc("Department Staff Budget", b["name"], ignore_permissions=True)
        for ln in doc.lines or []:
            des = ln.get("designation") if isinstance(ln, dict) else ln.designation
            hc = int((ln.get("budgeted_headcount") if isinstance(ln, dict) else ln.budgeted_headcount) or 0)
            cost = float((ln.get("annual_cost") if isinstance(ln, dict) else ln.annual_cost) or 0)
            fl = staffing.filled(b["department"], des); cm = staffing.committed(b["department"], des, start=b["from_date"], end=b["to_date"])
            rb.row({"department": b["department"], "budget": b["name"], "designation": des, "budgeted": hc, "filled": fl, "committed": cm,
                    "vacant": max(0, hc - fl - cm), "over": max(0, fl + cm - hc), "annual_cost": cost})
    rb.total("TOTAL")
    return rb.build(filters=[("As of", day), ("Department", filters.get("department") or "All")])
