from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I
from sqlalchemy import select

from velora import db
from velora.db.system import role_conflict


def execute(filters):
    pairs = I.query(select(role_conflict))
    rb = ReportBuilder("Role Conflicts in Use", [Column("user", "User"), Column("role_a", "Role A"), Column("role_b", "Role B"), Column("reason", "Why it matters")])
    for u in I.role_rows():
        have = set(u.get("roles") or [])
        for p in pairs:
            if p["role_a"] in have and p["role_b"] in have:
                rb.row({"user": u["user_email"], "role_a": p["role_a"], "role_b": p["role_b"], "reason": p.get("reason") or ""})
    note = [] if pairs else ["No conflicting role pairs are defined yet. Define them in Role Administration to make this report useful."]
    return rb.build(summary=[{"label": "Rules defined", "value": len(pairs), "fieldtype": "Int"}, {"label": "People in conflict", "value": len({r.values["user"] for r in rb.rows}), "fieldtype": "Int"}], notes=note)
