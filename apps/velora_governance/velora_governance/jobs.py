from datetime import date
from velora import get_doc, get_list

def mark_overdue_actions():
    """Daily idempotent job: mark due-past open/in-progress governance actions Overdue."""
    today = date.today()
    rows = get_list("Board Action", filters=[["due_date", "<", today], ["action_status", "in", ["Open", "In Progress"]]], fields=["name"], limit=1000, ignore_permissions=True)
    updated = 0
    for row in rows:
        action = get_doc("Board Action", row["name"], ignore_permissions=True)
        if action.action_status in ("Open", "In Progress") and action.due_date and action.due_date < today:
            action.action_status = "Overdue"
            action.save(ignore_permissions=True)
            updated += 1
    return {"updated": updated, "checked_on": today.isoformat()}

def daily_governance_maintenance():
    """Daily idempotent status maintenance for overdue obligations, filings and registers."""
    today = date.today()
    result = {"actions": 0, "obligations": 0, "filings": 0, "annual_returns": 0, "correspondence": 0, "registers": 0, "policies": 0, "controls": 0, "training": 0, "sustainability_tasks": 0}
    rules = [
        ("Board Action", "due_date", "action_status", ["Open", "In Progress"], "Overdue", "actions"),
        ("Governance Obligation", "due_date", "obligation_status", ["Open", "In Progress"], "Overdue", "obligations"),
        ("Corporate Filing", "due_date", "filing_status", ["Draft", "Ready", "Rejected"], "Overdue", "filings"),
        ("Annual Return", "due_date", "annual_return_status", ["Draft", "Ready", "Submitted"], "Overdue", "annual_returns"),
        ("Regulatory Correspondence", "response_due_date", "correspondence_status", ["Open", "In Progress"], "Overdue", "correspondence"),
        ("Governance Policy", "next_review_date", "policy_status", ["Active"], "Under Review", "policies"),
        ("Director Training Record", "expiry_date", "training_status", ["Completed"], "Expired", "training"),
    ]
    for doctype, date_field, status_field, active_statuses, overdue_status, key in rules:
        rows = get_list(doctype, filters=[[date_field, "<", today], [status_field, "in", active_statuses]], fields=["name"], limit=1000, ignore_permissions=True)
        for row in rows:
            doc = get_doc(doctype, row["name"], ignore_permissions=True)
            if getattr(doc, status_field) in active_statuses and getattr(doc, date_field) and getattr(doc, date_field) < today:
                setattr(doc, status_field, overdue_status)
                doc.save(ignore_permissions=True)
                result[key] += 1
    rows = get_list("Statutory Register", filters=[["register_status", "=", "Active"], ["next_review_date", "<", today]], fields=["name"], limit=1000, ignore_permissions=True)
    for row in rows:
        doc = get_doc("Statutory Register", row["name"], ignore_permissions=True)
        if doc.register_status == "Active" and doc.next_review_date and doc.next_review_date < today:
            doc.register_status = "Under Review"
            doc.save(ignore_permissions=True)
            result["registers"] += 1
    rows = get_list("Governance Control", filters=[["control_status", "=", "Active"], ["next_test_date", "<", today]], fields=["name"], limit=1000, ignore_permissions=True)
    for row in rows:
        doc = get_doc("Governance Control", row["name"], ignore_permissions=True)
        if doc.control_status == "Active" and doc.next_test_date and doc.next_test_date < today:
            doc.control_status = "Review Due"
            doc.save(ignore_permissions=True)
            result["controls"] += 1
    rows = get_list("Sustainability Data Collection Task", filters=[["due_date", "<", today], ["task_status", "in", ["Open", "In Progress"]]], fields=["name"], limit=1000, ignore_permissions=True)
    for row in rows:
        doc = get_doc("Sustainability Data Collection Task", row["name"], ignore_permissions=True)
        if doc.task_status in ("Open", "In Progress") and doc.due_date and doc.due_date < today:
            doc.task_status = "Overdue"
            doc.save(ignore_permissions=True)
            result["sustainability_tasks"] += 1
    return {"updated": result, "checked_on": today.isoformat()}


def daily_generate_governance_automation():
    """Generate and persist idempotent governance reminder/escalation actions."""
    from velora_governance.governance.services.governance_automation_scheduler import generate_and_persist_actions
    from velora_governance.governance.services.governance_automation_configuration import load_configuration
    config = load_configuration()
    if not config.get("automation_enabled"):
        return {"disabled": True, "reason": "automation_disabled_by_configuration"}
    rules = {"reminder_days_before": config["reminder_days_before"],
             "escalation_days_overdue": config["escalation_days_overdue"],
             "terminal_statuses": config["terminal_statuses"]}
    return generate_and_persist_actions(rules=rules, owner_field_mapping=config.get("owner_field_mapping"), recipient_overrides=config.get("recipient_overrides"),
                                        limit_per_doctype=config.get("max_batch_size", 100))


def hourly_execute_governance_automation():
    """Execute queued in-app governance notifications and process retries."""
    from velora_governance.governance.services.governance_automation_scheduler import run_queued_automation
    from velora_governance.governance.services.governance_automation_configuration import load_configuration
    config = load_configuration()
    if not config.get("automation_enabled"):
        return {"disabled": True, "reason": "automation_disabled_by_configuration"}
    return run_queued_automation(max_items=config.get("max_batch_size", 100),
        max_attempts=config.get("max_attempts", 5), retry_base_minutes=config.get("retry_base_minutes", 5),
        retry_max_hours=config.get("retry_max_hours", 24))


def hourly_governance_exception_escalations():
    """Hourly exception escalation; notification failures are isolated per exception."""
    from velora_governance.governance.services.governance_exception_escalation_runtime import run_exception_escalations
    return run_exception_escalations()
