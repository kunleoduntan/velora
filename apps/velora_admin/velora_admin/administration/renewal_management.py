"""Renewal management services. Notification delivery is delegated to Framework."""
from datetime import date
import json

from .doctype.renewal_register.renewal_register import renewal_state, renewal_alert_due


def _frappe():
    try:
        import frappe
        return frappe
    except Exception as exc:
        raise RuntimeError("Renewal management requires the Velora runtime") from exc


def renewal_dashboard(today=None):
    frappe = _frappe()
    today = today or date.today()
    records = frappe.get_all("Renewal Register", filters={"status": ["in", ["Active", "Renewal In Progress"]]},
        fields=["name", "renewal_title", "renewal_category", "expiry_date", "renewal_lead_days", "department", "responsible_officer", "status"], limit_page_length=10000)
    result = {"expired": [], "due_soon": [], "upcoming": [], "total_active": len(records)}
    for row in records:
        state = renewal_state(row.expiry_date, today)
        row.update(state)
        if state["state"] == "Expired":
            result["expired"].append(row)
        elif renewal_alert_due(row.expiry_date, row.renewal_lead_days, today):
            result["due_soon"].append(row)
        else:
            result["upcoming"].append(row)
    return result


def daily_renewal_scan(today=None):
    """Collect renewal events idempotently for downstream Framework notification rules.

    This intentionally does not insert Notification Log records or send email. The exact
    Framework Notification Engine API must be available before dispatch is enabled.
    """
    frappe = _frappe()
    today = today or date.today()
    records = frappe.get_all("Renewal Register", filters={"status": ["in", ["Active", "Renewal In Progress"]]},
        fields=["name", "renewal_title", "renewal_category", "expiry_date", "notification_schedule_json", "department", "responsible_officer", "company_or_entity"], limit_page_length=10000)
    events = []
    for row in records:
        if not row.expiry_date:
            continue
        days = renewal_state(row.expiry_date, today)["days_remaining"]
        try:
            raw_schedule = json.loads(row.notification_schedule_json or "[30,14,7,1,0]")
            if not isinstance(raw_schedule, list):
                raise ValueError("Notification schedule must be a JSON list")
            schedule = sorted({int(value) for value in raw_schedule if int(value) >= 0}, reverse=True)
        except (TypeError, ValueError, json.JSONDecodeError):
            schedule = [30, 14, 7, 1, 0]
        if days in schedule or days < 0:
            milestone = days if days >= 0 else "overdue"
            events.append({"event": "renewal_due", "record": row.name, "title": row.renewal_title,
                "category": row.renewal_category, "days_remaining": days, "expiry_date": str(row.expiry_date),
                "department": row.department, "responsible_officer": row.responsible_officer,
                "entity": row.company_or_entity, "event_date": today.isoformat(),
                "idempotency_key": f"renewal:{row.name}:{milestone}:{today.isoformat()}"})
    return {"scan_date": today.isoformat(), "events": events,
        "dispatch_status": "PENDING_FRAMEWORK_NOTIFICATION_ENGINE_API",
        "message": "Renewal events collected. No notifications dispatched until the Framework Notification Engine adapter is verified."}
