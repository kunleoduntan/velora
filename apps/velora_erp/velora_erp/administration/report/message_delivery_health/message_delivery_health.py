from datetime import date, timedelta
from decimal import Decimal

from velora import get_list
from velora.reporting import Column, ReportBuilder

from velora_erp.administration import insight as I
from collections import Counter

from velora.meta.registry import registry


def execute(filters):
    days = int((filters or {}).get("days") or 30)
    since = (date.today() - timedelta(days=days)).isoformat()
    rb = ReportBuilder("Message Delivery Health", [Column("area", "Area"), Column("kind", "Channel or kind"), Column("status", "Status"), Column("count", "Messages", "Int"), Column("share", "Share", "Percent"), Column("hint", "What it means")])
    hints = {"Failed": "Check SMTP or the gateway and the error text.", "Queued": "Waiting to be sent.", "Held": "Waiting for someone to release it.", "Sent": "Delivered to the mail server or gateway.", "Opted Out": "The person asked not to be messaged.", "No Address": "Add an email or phone to the record.", "Not Sent": "Messaging is not set up."}
    bad = 0
    for doctype, area, kind_f, date_f in (("Notification Delivery", "Notifications", "channel", "creation"), ("Engagement Log", "Greetings", "kind", "moment_date")):
        if not registry.exists(doctype):
            continue
        rows = get_list(doctype, filters=[[date_f, ">=", since]], fields=[kind_f, "status"], limit=500000, ignore_permissions=True)
        total = len(rows)
        for (kind, status), n in sorted(Counter((r[kind_f], r["status"]) for r in rows).items(), key=lambda kv: -kv[1]):
            if status in ("Failed", "No Address", "Not Sent"):
                bad += n
            rb.row({"area": area, "kind": kind or "", "status": status, "count": n, "share": I.pct(n, total), "hint": hints.get(status, "")})
    return rb.build(summary=[{"label": "Messages", "value": sum(r.values["count"] for r in rb.rows), "fieldtype": "Int"}, {"label": "Need attention", "value": bad, "fieldtype": "Int"}])
