from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I
from velora.meta.registry import registry


def _p(p, k):
    return bool(p.get(k) if isinstance(p, dict) else getattr(p, k, False))


def execute(filters):
    stats = {}
    for m in registry.all():
        for p in m.permissions:
            role = p.get("role") if isinstance(p, dict) else getattr(p, "role", None)
            if not role:
                continue
            s = stats.setdefault(role, dict(read=set(), write=set(), submit=set(), cancel=set(), delete=set()))
            for k in s:
                if _p(p, k) or (k == "write" and _p(p, "create")):
                    s[k].add(m.name)
    rb = ReportBuilder("Access by Role", [Column("role", "Role"), Column("read", "Can read", "Int"), Column("write", "Can change", "Int"), Column("submit", "Can submit", "Int"),
                                          Column("cancel", "Can cancel", "Int"), Column("delete", "Can delete", "Int"), Column("level", "Power level"), Column("advice", "What to consider")])
    for role, s in sorted(stats.items(), key=lambda kv: -(len(kv[1]["delete"]) * 4 + len(kv[1]["cancel"]) * 3 + len(kv[1]["submit"]) * 2 + len(kv[1]["write"]))):
        level = "Administrator" if len(s["delete"]) >= 10 else "Approver" if s["submit"] or s["cancel"] else "Operator" if s["write"] else "Read-only"
        advice = {"Administrator": "Give to as few people as possible.", "Approver": "Pair with a separate preparer role.", "Operator": "Normal day-to-day access.", "Read-only": "Safe for auditors and managers."}[level]
        rb.row({"role": role, "read": len(s["read"]), "write": len(s["write"]), "submit": len(s["submit"]), "cancel": len(s["cancel"]), "delete": len(s["delete"]), "level": level, "advice": advice})
    admins = sum(1 for r in rb.rows if r.values["level"] == "Administrator")
    return rb.build(summary=[{"label": "Roles", "value": len(rb.rows), "fieldtype": "Int"}, {"label": "Administrator-level roles", "value": admins, "fieldtype": "Int"}])
