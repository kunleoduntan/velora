"""Event-driven exception detection for allow-listed governance source documents."""
from __future__ import annotations
from datetime import date
import hashlib

from velora_governance.governance.services.governance_automation_scheduler import SOURCE_DOCTYPES, _get_api
from velora_governance.governance.services.governance_automation_configuration import load_configuration
from velora_governance.governance.services.governance_velora_runtime import VeloraGovernanceExecutionRepository

SOURCE_MAP = {entry[0]: entry for entry in SOURCE_DOCTYPES}


def _as_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def enqueue_overdue_exception(doc, *, api=None, repository=None, today=None, configuration=None):
    """Enqueue an idempotent overdue exception notification after a source save.

    Only allow-listed source doctypes and known status/date/owner fields are used.
    This function does not change document status or invoke approval transitions.
    """
    doctype = getattr(doc, "doctype", None) or (doc.get("doctype") if isinstance(doc, dict) else None)
    if doctype not in SOURCE_MAP:
        return {"status": "ignored", "reason": "doctype_not_allowlisted"}
    data = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc or {})
    entry = SOURCE_MAP[doctype]
    _, due_field, status_field, active_statuses, title_field, default_owner = entry
    config = configuration or load_configuration(api)
    if not config.get("automation_enabled"):
        return {"status": "ignored", "reason": "automation_disabled"}
    due = _as_date(data.get(due_field))
    today = today or date.today()
    if not due or due >= today or data.get(status_field) not in active_statuses:
        return {"status": "ignored", "reason": "not_overdue_active_item"}
    owner_field = (config.get("owner_field_mapping") or {}).get(doctype, default_owner)
    owner = data.get(owner_field) if owner_field else None
    owner = owner or (config.get("recipient_overrides") or {}).get(doctype)
    if not owner:
        return {"status": "ignored", "reason": "recipient_missing"}
    source_name = str(data.get("name") or "")
    modified = str(data.get("modified") or data.get("creation") or "event")
    key_material = f"{doctype}|{source_name}|overdue_exception|{modified}|{today.isoformat()}"
    key = hashlib.sha256(key_material.encode()).hexdigest()
    title = data.get(title_field) or source_name or doctype
    action = {
        "item_type": doctype, "item_id": source_name, "title": str(title),
        "due_date": due.isoformat(), "days_until_due": (due-today).days,
        "action_type": "notification", "trigger_kind": "overdue_exception", "owner": owner,
        "recipient_fallback": not bool(data.get(owner_field)) if owner_field else True,
        "message": f"Governance exception: {title} is overdue since {due.isoformat()}.",
        "idempotency_key": key, "correlation_id": key[:24], "event_triggered": True,
    }
    repo = repository or VeloraGovernanceExecutionRepository(api=_get_api(api))
    result = repo.insert_if_absent({"idempotency_key": key, "action": action,
        "status": "Queued", "attempts": 0, "actor": "Event Trigger", "result": {}})
    return {"status": "queued" if result.get("created") else "duplicate_suppressed",
            "idempotency_key": key, "item": source_name}


def on_source_update(doc, method=None):
    """Queue notification and persist exception for overdue active allowlisted records.

    Persistence is best-effort so governance source saves are not blocked by the
    exception subsystem. Notification queue failures remain isolated as well.
    """
    try:
        notification = enqueue_overdue_exception(doc)
    except Exception:
        notification = {"status": "failed", "reason": "event_trigger_error"}
    try:
        doctype = getattr(doc, "doctype", None) or (doc.get("doctype") if isinstance(doc, dict) else None)
        if doctype not in SOURCE_MAP:
            return notification
        data = doc.as_dict() if hasattr(doc, "as_dict") else dict(doc or {})
        entry = SOURCE_MAP[doctype]
        _, due_field, status_field, active_statuses, title_field, _default_owner = entry
        due = _as_date(data.get(due_field)); today = date.today()
        if not due or due >= today or data.get(status_field) not in active_statuses:
            return notification
        from velora_governance.governance.services.governance_exception_persistence import upsert_exception
        from velora_governance.runtime import host as frappe
        payload = {"source_doctype": doctype, "source_name": str(data.get("name") or ""),
            "exception_type": "Overdue Governance Item", "title": str(data.get(title_field) or data.get("name") or doctype),
            "description": f"Source record is overdue since {due.isoformat()}.", "due_date": due.isoformat()}
        if frappe.has_permission("Governance Exception", "create") and frappe.has_permission("Governance Exception", "write"):
            upsert_exception(payload, frappe_api=frappe)
    except Exception:
        # Exception persistence failure is intentionally non-fatal to source save.
        pass
    return notification
