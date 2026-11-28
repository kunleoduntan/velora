"""Configurable elapsed-time exception escalation and workload intelligence."""
from datetime import datetime, timezone

ACTIVE_STATUSES = {"Open", "Assigned", "In Progress", "Escalated", "Pending Evidence"}


def parse_intervals(value):
    values = [int(x.strip()) for x in str(value or "").split(",") if x.strip()]
    if not values or any(x <= 0 for x in values) or values != sorted(set(values)):
        raise ValueError("escalation_intervals_must_be_positive_and_increasing")
    return values


def determine_due_stage(created, now, intervals, completed_stages=0):
    """Return the next 1-based stage due by elapsed hours, or None."""
    created = created if isinstance(created, datetime) else datetime.fromisoformat(str(created))
    now = now if isinstance(now, datetime) else datetime.fromisoformat(str(now))
    if created.tzinfo and not now.tzinfo:
        now = now.replace(tzinfo=created.tzinfo)
    if now.tzinfo and not created.tzinfo:
        created = created.replace(tzinfo=now.tzinfo)
    elapsed = (now - created).total_seconds() / 3600
    for stage, threshold in enumerate(parse_intervals(intervals), start=1):
        if stage > completed_stages and elapsed >= threshold:
            return stage
    return None


def escalation_recipients(targets, stage):
    users = targets.get(str(stage), targets.get(stage, [])) if isinstance(targets, dict) else []
    if not isinstance(users, list):
        return []
    return list(dict.fromkeys(str(user).strip() for user in users if str(user).strip()))


def workload_metrics(records):
    """Pure aggregate of exception workload and aging."""
    active = [r for r in records if r.get("status") in ACTIVE_STATUSES]
    by_owner = {}
    aging = {"0_7": 0, "8_30": 0, "31_60": 0, "61_plus": 0}
    escalated = 0
    for row in active:
        owner = row.get("assigned_to") or "Unassigned"
        by_owner[owner] = by_owner.get(owner, 0) + 1
        age = max(0, int(row.get("age_days") or row.get("overdue_days") or 0))
        if age <= 7: aging["0_7"] += 1
        elif age <= 30: aging["8_30"] += 1
        elif age <= 60: aging["31_60"] += 1
        else: aging["61_plus"] += 1
        if row.get("status") == "Escalated": escalated += 1
    return {"active": len(active), "escalated": escalated, "unassigned": by_owner.get("Unassigned", 0),
            "by_owner": by_owner, "aging_buckets": aging}
