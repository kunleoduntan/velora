from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I
from collections import Counter
from datetime import datetime

from sqlalchemy import select

from velora import db
from velora.db.system import version


def execute(filters):
    days = int((filters or {}).get("days") or 30)
    since = datetime.combine(date.today() - timedelta(days=days), datetime.min.time())
    rows = I.query(select(version.c.owner, version.c.ref_doctype, version.c.creation).where(version.c.creation >= since))
    by_user, by_form, last, form_of = Counter(), Counter(), {}, {}
    for r in rows:
        by_user[r["owner"]] += 1; by_form[r["ref_doctype"]] += 1
        form_of.setdefault(r["owner"], Counter())[r["ref_doctype"]] += 1
        if r["owner"] not in last or r["creation"] > last[r["owner"]]:
            last[r["owner"]] = r["creation"]
    total = sum(by_user.values())
    rb = ReportBuilder("Activity Pulse", [Column("user", "User"), Column("changes", "Changes", "Int"), Column("share", "Share of all", "Percent"), Column("form", "Most-edited form"), Column("last", "Last active", "Datetime")])
    for u, n in by_user.most_common():
        rb.row({"user": u, "changes": n, "share": I.pct(n, total), "form": form_of[u].most_common(1)[0][0], "last": last[u]})
    quiet = [r["user_email"] for r in I.role_rows() if r["user_email"] not in by_user and r.get("roles")]
    notes = [f"No activity in {days} days: " + ", ".join(sorted(quiet)[:15]) + (" ..." if len(quiet) > 15 else "")] if quiet else []
    busy = by_form.most_common(1)[0] if by_form else ("none", 0)
    return rb.build(summary=[{"label": "Changes", "value": total, "fieldtype": "Int"}, {"label": "Active people", "value": len(by_user), "fieldtype": "Int"}, {"label": "Busiest form: " + busy[0], "value": busy[1], "fieldtype": "Int"}, {"label": "Quiet users", "value": len(quiet), "fieldtype": "Int"}], notes=notes)
