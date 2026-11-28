"""Governance task automation runtime: safe, idempotent action planning."""
from datetime import date
from .governance_automation import evaluate_governance_items, build_automation_message

def run_task_automation(items, *, today=None, rules=None, templates=None, existing_keys=None):
    """Plan automation actions, suppressing already-issued action keys. Does not dispatch."""
    result = evaluate_governance_items(items, today=today, rules=rules)
    existing = set(existing_keys or [])
    templates = templates or {}
    planned = []
    suppressed = 0
    for action in result["actions"]:
        key = f'{action.get("item_id")}:{action.get("action_type")}:{action.get("due_date")}:{result["evaluated_on"]}'
        if key in existing:
            suppressed += 1
            continue
        action = dict(action)
        action["idempotency_key"] = key
        action["message"] = build_automation_message(action, template=templates.get(action.get("action_type")))
        planned.append(action)
    result.update({"planned_actions": planned, "suppressed_duplicates": suppressed, "dispatch_ready": False,
                  "runtime_note": "Planning only; delivery must be performed by the configured notification/workflow runtime."})
    return result
