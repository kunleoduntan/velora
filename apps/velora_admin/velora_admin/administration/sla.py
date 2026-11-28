"""Daily Request SLA and escalation maintenance."""
from datetime import datetime

from velora import get_list, get_doc
from velora.meta.registry import registry


def daily_maintenance():
    """Update SLA states and set escalation flags. Notifications are optional."""
    if not registry.exists("Request"):
        return {"scanned": 0, "updated": 0, "escalated": 0}
    docs = get_list("Request", filters={"status": "Pending Approval", "docstatus": 1},
                   fields=["name", "sla_due_datetime", "sla_status", "escalated", "escalated_on", "current_level"],
                   limit=5000, ignore_permissions=True)
    now = datetime.now()
    updated = escalated = 0
    for row in docs:
        try:
            doc = get_doc("Request", row["name"], ignore_permissions=True)
            due = getattr(doc, "sla_due_datetime", None)
            if not due:
                continue
            due_dt = datetime.fromisoformat(str(due))
            state = "Overdue" if due_dt < now else "Due Soon" if (due_dt-now).total_seconds() <= 24*3600 else "On Track"
            changed = state != getattr(doc, "sla_status", None)
            doc.sla_status = state
            if state == "Overdue" and not getattr(doc, "escalated", False):
                doc.escalated = 1
                doc.escalated_on = now.strftime("%Y-%m-%d %H:%M:%S")
                escalated += 1
                changed = True
                _notify_escalation(doc)
            if changed:
                doc.save(ignore_permissions=True)
                updated += 1
        except Exception:
            # One malformed record must not stop the daily batch.
            continue
    return {"scanned": len(docs), "updated": updated, "escalated": escalated}


def _notify_escalation(doc):
    """Create in-app notifications if Notification Log is installed and compatible."""
    if not registry.exists("Notification Log"):
        return
    try:
        from velora import new_doc
        targets = []
        if registry.exists("Approval Escalation Rule"):
            rules = get_list("Approval Escalation Rule", filters={"is_active": 1, "scope": "Request"},
                            fields=["escalate_to_user", "escalate_to_role"], limit=100, ignore_permissions=True)
            targets.extend([r.get("escalate_to_user") for r in rules if r.get("escalate_to_user")])
            for rule in rules:
                role = rule.get("escalate_to_role")
                if role:
                    try:
                        users = get_list("User Role", filters={"role": role}, fields=["user"], limit=500, ignore_permissions=True)
                        targets.extend([x.get("user") for x in users if x.get("user")])
                    except Exception:
                        pass
        if not targets:
            return
        meta = registry.get("Notification Log")
        field_names = {f.fieldname for f in meta.fields}
        for user in sorted(set(targets)):
            payload = {}
            for key, value in {
                "user": user,
                "subject": f"Request overdue: {doc.name}",
                "message": f"Request {doc.name} is overdue and requires attention.",
                "ref_doctype": "Request",
                "ref_name": doc.name,
                "document_type": "Request",
                "document_name": doc.name,
                "type": "Alert",
            }.items():
                if key in field_names:
                    payload[key] = value
            if payload:
                new_doc("Notification Log", **payload).insert(ignore_permissions=True)
    except Exception:
        # Notification schema/app is optional; escalation flags remain authoritative.
        return
