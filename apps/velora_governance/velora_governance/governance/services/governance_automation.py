"""Pure governance automation evaluation engine (configuration-driven)."""
from datetime import date, datetime

DEFAULT_RULES = {
    "reminder_days_before": [30, 14, 7, 3, 1, 0],
    "escalation_days_overdue": [1, 7, 14, 30],
    "terminal_statuses": ["Completed", "Cancelled", "Closed", "Resolved"],
}

def _as_date(value):
    if isinstance(value, date): return value
    if isinstance(value, datetime): return value.date()
    if not value: return None
    return date.fromisoformat(str(value)[:10])


def evaluate_governance_items(items, *, today=None, rules=None):
    """Return deterministic reminder/escalation candidates without sending them.

    Each item may contain id, title, due_date, status, owner, entity, item_type.
    Rules are overridable and may be supplied by Governance Automation Settings.
    """
    today = _as_date(today) or date.today()
    cfg = {**DEFAULT_RULES, **(rules or {})}
    terminal = set(cfg.get("terminal_statuses", []))
    reminder_days = set(int(x) for x in cfg.get("reminder_days_before", []))
    escalation_days = sorted(set(int(x) for x in cfg.get("escalation_days_overdue", [])))
    actions = []
    for item in items or []:
        due = _as_date(item.get("due_date"))
        if not due or item.get("status") in terminal: continue
        days = (due - today).days
        action = None
        if days in reminder_days: action = "Reminder"
        elif days < 0 and abs(days) in escalation_days: action = "Escalation"
        elif days < 0: action = "Overdue Review"
        if action:
            actions.append({"item_id": item.get("id"), "title": item.get("title"),
                "item_type": item.get("item_type"), "entity": item.get("entity"),
                "owner": item.get("owner"), "due_date": due.isoformat(),
                "days_until_due": days, "action_type": action,
                "severity": "Critical" if days <= -30 else "High" if days < 0 else "Medium",
                "routing_key": item.get("routing_key")})
    priority = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    actions.sort(key=lambda a: (priority.get(a["severity"], 9), a["days_until_due"], str(a.get("title") or "")))
    return {"evaluated_on": today.isoformat(), "items_evaluated": len(items or []),
        "actions_generated": len(actions), "actions": actions}


def build_automation_message(action, *, template=None):
    """Resolve a safe plain-text notification using an optional template."""
    template = template or "{title} is due {due_date}. Status: {action_type}. Owner: {owner}."
    values = {k: str(action.get(k) or "Not assigned") for k in ["title", "due_date", "action_type", "owner", "entity", "item_type"]}
    return template.format(**values)
