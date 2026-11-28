"""Native runtime automation generation, dispatch, and retry operations.

The scheduler generates and persists idempotent reminders/escalations. Dispatch
uses the framework's in-app Notification Log as the concrete native channel.
This module intentionally does not trigger approval/workflow transitions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib

from velora_governance.governance.services.governance_automation import evaluate_governance_items
from velora_governance.governance.services.governance_velora_runtime import VeloraGovernanceExecutionRepository

SOURCE_DOCTYPES = (
    ("Board Action", "due_date", "action_status", ("Open", "In Progress", "Overdue"), "action_title", "assigned_owner"),
    ("Governance Obligation", "due_date", "obligation_status", ("Open", "In Progress", "Overdue"), "requirement", "responsible_owner"),
    ("Corporate Filing", "due_date", "filing_status", ("Draft", "Ready", "Rejected", "Overdue"), "filing_requirement", "responsible_owner"),
    ("Annual Return", "due_date", "annual_return_status", ("Draft", "Ready", "Submitted", "Overdue"), "reporting_year", None),
    ("Regulatory Correspondence", "response_due_date", "correspondence_status", ("Open", "In Progress", "Overdue"), "subject", "responsible_owner"),
    ("Sustainability Data Collection Task", "due_date", "task_status", ("Open", "In Progress", "Overdue"), "metric", "responsible_owner"),
)


def _get_api(api=None):
    if api:
        if isinstance(api, dict):
            return api
        return {name: getattr(api, name) for name in ("get_list", "get_doc", "new_doc") if callable(getattr(api, name, None))}
    from velora_governance.runtime import host
    return {"get_list": host.get_list, "get_doc": host.get_doc, "new_doc": host.new_doc}


def collect_due_items(api=None, *, today=None, limit_per_doctype=1000, owner_field_mapping=None):
    """Read a bounded allow-list of governance records into evaluator inputs."""
    api = _get_api(api)
    today = today or date.today()
    items = []
    owner_field_mapping = owner_field_mapping or {}
    for doctype, due_field, status_field, statuses, title_field, default_owner_field in SOURCE_DOCTYPES:
        owner_field = owner_field_mapping.get(doctype, default_owner_field)
        fields = ["name", due_field, status_field, title_field, "governance_entity"]
        if owner_field:
            fields.append(owner_field)
        rows = api["get_list"](doctype, filters=[[status_field, "in", list(statuses)]], fields=fields,
                              limit=max(1, min(int(limit_per_doctype), 1000)), ignore_permissions=True)
        for row in rows or []:
            due = row.get(due_field)
            if not due:
                continue
            try:
                due_date = due if isinstance(due, date) else date.fromisoformat(str(due)[:10])
            except (TypeError, ValueError):
                continue
            items.append({
                "id": row.get("name"), "title": row.get(title_field) or row.get("name"),
                "due_date": due_date, "status": row.get(status_field),
                "owner": row.get(owner_field) if owner_field else None, "entity": row.get("governance_entity"),
                "item_type": doctype, "routing_key": row.get(owner_field),
            })
    return items


def _idempotency_key(action):
    identity = "|".join(str(action.get(k) or "") for k in
                        ("item_type", "item_id", "action_type", "due_date", "days_until_due"))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def generate_and_persist_actions(*, api=None, repository=None, today=None, rules=None, owner_field_mapping=None, recipient_overrides=None, limit_per_doctype=1000):
    today = today or date.today()
    native_api = _get_api(api)
    items = collect_due_items(api=native_api, today=today, owner_field_mapping=owner_field_mapping, limit_per_doctype=limit_per_doctype)
    evaluation = evaluate_governance_items(items, today=today, rules=rules)
    repo = repository or VeloraGovernanceExecutionRepository(api=native_api)
    persisted = 0
    duplicates = 0
    failures = 0
    missing_owner = 0
    recipient_overrides = recipient_overrides or {}
    for candidate in evaluation["actions"]:
        resolved_owner = candidate.get("owner") or recipient_overrides.get(candidate.get("item_type"))
        if not resolved_owner:
            missing_owner += 1
            continue
        action = dict(candidate)
        action["owner"] = resolved_owner
        action["recipient_fallback"] = not bool(candidate.get("owner"))
        action["item_id"] = candidate.get("item_id")
        action["idempotency_key"] = _idempotency_key(action)
        action["correlation_id"] = action["idempotency_key"][:24]
        # Reminder and escalation candidates are in-app notifications only.
        action["action_type"] = "notification"
        action["message"] = (f"{candidate.get('title')} — {candidate.get('action_type')}; "
                             f"due {candidate.get('due_date')} (days: {candidate.get('days_until_due')}).")
        try:
            result = repo.insert_if_absent({"idempotency_key": action["idempotency_key"],
                "action": action, "status": "Queued", "attempts": 0, "actor": "Scheduler", "result": {}})
            if result.get("created"):
                persisted += 1
            else:
                duplicates += 1
        except Exception:
            failures += 1
    return {"evaluated": len(items), "candidates": evaluation["actions_generated"],
            "persisted": persisted, "duplicates": duplicates, "failures": failures, "missing_owner": missing_owner,
            "evaluated_on": evaluation["evaluated_on"]}


def dispatch_in_app_notification(action, *, api=None):
    """Create a native in-app Notification Log; no external email/SMS is sent."""
    api = _get_api(api)
    recipient = str(action.get("owner") or action.get("routing_key") or "").strip()
    if not recipient:
        raise ValueError("notification_recipient_required")
    user_rows = api["get_list"]("User", filters={"name": recipient}, fields=["name", "enabled"], limit=1, ignore_permissions=True)
    if not user_rows:
        employee_rows = api["get_list"]("Employee", filters={"name": recipient}, fields=["user_id"], limit=1, ignore_permissions=True)
        employee_user = (employee_rows or [{}])[0].get("user_id")
        if employee_user:
            user_rows = api["get_list"]("User", filters={"name": employee_user}, fields=["name", "enabled"], limit=1, ignore_permissions=True)
            if user_rows:
                recipient = employee_user
    if not user_rows:
        raise ValueError("recipient_not_a_valid_user")
    user_row = user_rows[0]
    if user_row.get("enabled") in (0, False):
        raise ValueError("recipient_user_disabled")
    idempotency_key = str(action.get("idempotency_key") or "")
    subject = str(action.get("action_type") or "Governance Reminder")
    if idempotency_key:
        subject = f"{subject} [GAE-{idempotency_key[:12]}]"
    duplicate_rows = api["get_list"]("Notification Log", filters={"for_user": recipient, "subject": subject},
        fields=["name"], limit=1, ignore_permissions=True)
    if duplicate_rows:
        return {"notification_log": duplicate_rows[0].get("name"), "channel": "in_app",
                "recipient": recipient, "duplicate_suppressed": True}
    doc = api["new_doc"]("Notification Log")
    doc.subject = subject[:140]
    doc.email_content = str(action.get("message") or action.get("title") or "Governance item requires attention")
    doc.for_user = recipient
    doc.type = "Alert"
    if action.get("item_type") and action.get("item_id"):
        doc.document_type = str(action["item_type"])
        doc.document_name = str(action["item_id"])
    doc.insert(ignore_permissions=True)
    return {"notification_log": getattr(doc, "name", None), "channel": "in_app", "recipient": recipient}


def run_queued_automation(*, repository=None, api=None, max_items=100, max_attempts=5, retry_base_minutes=5, retry_max_hours=24, now=None):
    """Execute queued notifications, with capped exponential retry on failures."""
    now = now or datetime.now(timezone.utc)
    native_api = _get_api(api) if api is not None else None
    repo = repository or VeloraGovernanceExecutionRepository(api=native_api)
    try:
        rows = repo.list_records(status=["Queued", "Retry Pending"], limit=max(1, min(int(max_items), 250)))
    except TypeError:  # Compatibility with simple injected repositories used in tests.
        rows = repo.list_records(limit=max(1, min(int(max_items), 250)))
    outcomes = {"processed": 0, "completed": 0, "failed": 0, "retry_pending": 0, "skipped": 0}
    for row in rows:
        status = row.get("status")
        if status not in ("Queued", "Retry Pending"):
            outcomes["skipped"] += 1
            continue
        retry_at = row.get("next_retry_at")
        if status == "Retry Pending" and retry_at:
            try:
                retry_dt = retry_at if isinstance(retry_at, datetime) else datetime.fromisoformat(str(retry_at).replace("Z", "+00:00"))
                if retry_dt.tzinfo is None:
                    retry_dt = retry_dt.replace(tzinfo=timezone.utc)
                if retry_dt > now:
                    outcomes["skipped"] += 1
                    continue
            except (TypeError, ValueError):
                pass
        key = row.get("idempotency_key")
        attempts = int(row.get("attempts") or 0)
        outcomes["processed"] += 1
        if attempts >= max_attempts:
            repo.update_status(key, "Failed", result={"reason": "max_attempts_reached"},
                              error="Maximum retry attempts reached", attempts=attempts)
            outcomes["failed"] += 1
            continue
        repo.update_status(key, "Running", result={}, attempts=attempts + 1)
        try:
            action = row.get("action") or {}
            if action.get("action_type") != "notification":
                raise ValueError("unsupported_scheduled_action")
            result = dispatch_in_app_notification(action, api=api)
            repo.update_status(key, "Completed", result=result, attempts=attempts + 1)
            outcomes["completed"] += 1
        except Exception as exc:
            delay_minutes = min(1440, 5 * (2 ** attempts))
            next_retry = now + timedelta(minutes=delay_minutes)
            new_status = "Retry Pending" if attempts + 1 < max_attempts else "Failed"
            repo.update_status(key, new_status, result={}, error=f"{type(exc).__name__}: {exc}",
                              attempts=attempts + 1, next_retry_at=next_retry.isoformat())
            outcomes["failed"] += 1
            if new_status == "Retry Pending":
                outcomes["retry_pending"] += 1
    return outcomes
