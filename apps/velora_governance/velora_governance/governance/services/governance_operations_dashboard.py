"""Governance operations dashboard aggregation (permission-scoped inputs expected)."""
from collections import Counter


def build_governance_operations_dashboard(*, actions=None, automation_runs=None, obligations=None,
                                        risks=None, controls=None, meetings=None, notifications=None):
    actions = list(actions or [])
    automation_runs = list(automation_runs or [])
    obligations = list(obligations or [])
    risks = list(risks or [])
    controls = list(controls or [])
    meetings = list(meetings or [])
    notifications = list(notifications or [])

    def count_status(rows, statuses):
        return sum(str(row.get("status", "")).lower() in statuses for row in rows)

    open_actions = count_status(actions, {"open", "in progress", "pending", "overdue"})
    overdue_actions = sum(bool(row.get("overdue")) or str(row.get("status", "")).lower() == "overdue" for row in actions)
    failed_runs = count_status(automation_runs, {"failed", "recording_failed", "error"})
    retryable_runs = sum(bool(row.get("retryable")) for row in automation_runs)
    overdue_obligations = sum(bool(row.get("overdue")) or str(row.get("status", "")).lower() == "overdue" for row in obligations)
    high_risks = sum(str(row.get("rating", row.get("risk_level", ""))).lower() in {"high", "critical", "very high"} for row in risks)
    control_failures = sum(str(row.get("test_result", row.get("status", ""))).lower() in {"failed", "ineffective", "unsatisfactory"} for row in controls)
    upcoming_meetings = sum(bool(row.get("upcoming")) for row in meetings)
    notification_failures = count_status(notifications, {"failed", "undelivered", "error"})
    owner_counts = Counter(str(row.get("owner") or "Unassigned") for row in actions if str(row.get("status", "")).lower() not in {"completed", "closed"})
    attention = []
    for row in actions:
        if row.get("overdue") or str(row.get("status", "")).lower() == "overdue":
            attention.append({"type": "action", "id": row.get("name", row.get("id")), "priority": "high", "reason": "overdue_action"})
    for row in automation_runs:
        if str(row.get("status", "")).lower() in {"failed", "recording_failed", "error"}:
            attention.append({"type": "automation", "id": row.get("name", row.get("id")), "priority": "high", "reason": "automation_failure", "retryable": bool(row.get("retryable"))})
    return {
        "kpis": {
            "open_actions": open_actions, "overdue_actions": overdue_actions,
            "automation_runs": len(automation_runs), "automation_failures": failed_runs,
            "retryable_automation_runs": retryable_runs, "open_obligations": count_status(obligations, {"open", "pending", "in progress"}),
            "overdue_obligations": overdue_obligations, "high_risks": high_risks,
            "control_failures": control_failures, "upcoming_meetings": upcoming_meetings,
            "notification_failures": notification_failures,
        },
        "open_actions_by_owner": dict(owner_counts),
        "attention_queue": attention,
        "attention_count": len(attention),
        "data_scope_note": "Inputs must already be filtered by the native permission layer.",
    }
