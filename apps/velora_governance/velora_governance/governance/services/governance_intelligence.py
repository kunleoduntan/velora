"""Governance operations intelligence: KPIs, priority queue and action follow-up."""
from collections import Counter

def build_governance_intelligence(*, tasks=None, actions=None, risks=None, obligations=None, meetings=None):
    tasks, actions, risks, obligations, meetings = map(lambda x: list(x or []), (tasks, actions, risks, obligations, meetings))
    def status_counts(rows, field): return dict(Counter(r.get(field) or "Unspecified" for r in rows))
    overdue = [r for r in tasks + actions + obligations if r.get("overdue") or r.get("status") == "Overdue"]
    open_actions = [r for r in actions if r.get("status") not in ("Completed", "Closed", "Cancelled")]
    upcoming = [r for r in tasks + actions + obligations if r.get("days_until_due") is not None and 0 <= int(r.get("days_until_due")) <= 30]
    risk_high = [r for r in risks if r.get("risk_level") in ("High", "Critical")]
    priority = []
    for r in overdue: priority.append({"type": r.get("record_type", "Governance Item"), "id": r.get("id"), "title": r.get("title"), "owner": r.get("owner"), "priority": "High", "reason": "Overdue"})
    for r in risk_high: priority.append({"type": "Risk", "id": r.get("id"), "title": r.get("title"), "owner": r.get("owner"), "priority": "High" if r.get("risk_level") == "Critical" else "Medium", "reason": f"{r.get('risk_level')} risk"})
    porder = {"High": 0, "Medium": 1, "Low": 2}
    priority.sort(key=lambda x: (porder.get(x["priority"], 9), str(x.get("title") or "")))
    return {"kpis": {"tasks": len(tasks), "actions_total": len(actions), "open_actions": len(open_actions),
        "overdue_items": len(overdue), "upcoming_30_days": len(upcoming), "risks_total": len(risks),
        "high_critical_risks": len(risk_high), "obligations_total": len(obligations), "meetings_total": len(meetings)},
        "task_status": status_counts(tasks, "status"), "action_status": status_counts(actions, "status"),
        "risk_status": status_counts(risks, "status"), "priority_queue": priority}
