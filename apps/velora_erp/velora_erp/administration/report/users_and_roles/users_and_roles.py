from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I

def execute(filters):
    filters = filters or {}
    rb = ReportBuilder("Users and Their Roles", [Column("user", "User"), Column("roles", "Roles"), Column("count", "Roles held", "Int"), Column("flag", "Review"), Column("granted_by", "Granted by"), Column("granted_on", "Granted on", "Date")])
    flagged = 0
    for r in sorted(I.role_rows(), key=lambda r: r["user_email"]):
        roles = list(r.get("roles") or [])
        flag = "No role: cannot do anything" if not roles else "Has System Manager: full control" if "System Manager" in roles else "Holds many roles (6+)" if len(roles) >= 6 else ""
        if flag:
            flagged += 1
        if filters.get("only_flagged") and not flag:
            continue
        rb.row({"user": r["user_email"], "roles": ", ".join(sorted(roles)), "count": len(roles), "flag": flag, "granted_by": r.get("granted_by") or "", "granted_on": I.day(r.get("granted_on"))})
    return rb.build(summary=[{"label": "Users", "value": len(rb.rows), "fieldtype": "Int"}, {"label": "To review", "value": flagged, "fieldtype": "Int"}])
