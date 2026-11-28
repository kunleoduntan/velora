"""Governance exception centre primitives: severity, routing, resolution, and KPIs.

These are deterministic policy helpers. Persistence and workflow transitions remain
owned by native Velora APIs and configured framework workflows.
"""
from collections import Counter
from datetime import date, datetime


SEVERITY_ORDER = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
ACTIVE_STATUSES = {"Open", "Assigned", "In Progress", "Escalated", "Pending Evidence"}
RESOLUTION_STATUSES = {"Open", "Assigned", "In Progress", "Escalated", "Pending Evidence", "Resolved", "Closed"}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def classify_exception(*, due_date=None, today=None, risk_score=None, exception_type=None):
    """Assign severity using transparent deterministic rules; explicit score wins."""
    today = today or date.today()
    due = _as_date(due_date)
    overdue_days = max(0, (today - due).days) if due else 0
    if risk_score is not None:
        try:
            score = max(0, min(100, int(risk_score)))
        except (TypeError, ValueError):
            score = 0
        severity = "Critical" if score >= 85 else "High" if score >= 65 else "Medium" if score >= 40 else "Low"
    elif overdue_days >= 30:
        severity = "Critical"
    elif overdue_days >= 14:
        severity = "High"
    elif overdue_days >= 7:
        severity = "Medium"
    elif overdue_days > 0:
        severity = "Low"
    else:
        severity = "Low"
    return {"severity": severity, "severity_rank": SEVERITY_ORDER[severity],
            "overdue_days": overdue_days, "risk_score": risk_score,
            "exception_type": str(exception_type or "Governance Exception")}


def route_exception(*, severity, routing_config=None, default_route=None):
    """Resolve severity route from explicit config; no implicit role assumptions."""
    config = routing_config or {}
    route = config.get(str(severity)) or config.get("default") or default_route
    if route is None or not str(route).strip():
        return {"route": None, "routing_status": "unconfigured"}
    return {"route": str(route).strip(), "routing_status": "configured"}


def transition_exception(status, target, *, actor=None, evidence_required=False, evidence=None):
    """Validate exception lifecycle transition; workflow authorization is external."""
    status, target = str(status or "Open"), str(target or "")
    allowed = {
        "Open": {"Assigned", "In Progress", "Escalated", "Resolved"},
        "Assigned": {"In Progress", "Escalated", "Resolved"},
        "In Progress": {"Pending Evidence", "Escalated", "Resolved"},
        "Escalated": {"Assigned", "In Progress", "Pending Evidence", "Resolved"},
        "Pending Evidence": {"In Progress", "Resolved"},
        "Resolved": {"Closed", "In Progress"},
        "Closed": set(),
    }
    if status not in RESOLUTION_STATUSES or target not in RESOLUTION_STATUSES:
        return {"valid": False, "reason": "unknown_status"}
    if target not in allowed.get(status, set()):
        return {"valid": False, "reason": "transition_not_allowed", "from": status, "to": target}
    if target in {"Resolved", "Closed"} and evidence_required and not str(evidence or "").strip():
        return {"valid": False, "reason": "resolution_evidence_required"}
    return {"valid": True, "from": status, "to": target, "actor": actor,
            "evidence": str(evidence).strip() if evidence else None}


def build_exception_centre(records=None, *, today=None):
    """Build KPIs and actionable list from already permission-filtered records."""
    today = today or date.today()
    rows = []
    counts = Counter()
    active = 0
    overdue = 0
    critical = 0
    for raw in records or []:
        row = dict(raw or {})
        status = str(row.get("status") or "Open")
        classification = classify_exception(due_date=row.get("due_date"), today=today,
            risk_score=row.get("risk_score"), exception_type=row.get("exception_type") or row.get("item_type"))
        row.update(classification)
        row["status"] = status
        row["is_active"] = status in ACTIVE_STATUSES
        counts[status] += 1
        active += int(row["is_active"])
        overdue += int(row["overdue_days"] > 0 and row["is_active"])
        critical += int(row["severity"] == "Critical" and row["is_active"])
        rows.append(row)
    rows.sort(key=lambda r: (not r["is_active"], -r["severity_rank"], -r["overdue_days"], str(r.get("title") or r.get("name") or "")))
    return {"total": len(rows), "active": active, "overdue_active": overdue,
            "critical_active": critical, "status_counts": dict(counts),
            "severity_counts": dict(Counter(r["severity"] for r in rows)),
            "exceptions": rows, "as_of": today.isoformat()}


def validate_escalation_policy(policy=None):
    """Validate configurable elapsed-time escalation steps."""
    policy = list(policy or [])
    normalized = []
    previous = -1
    for step in policy:
        try:
            after_hours = int(step.get("after_hours"))
        except (TypeError, ValueError, AttributeError):
            return {"valid": False, "reason": "after_hours_must_be_integer"}
        route = str(step.get("route") or "").strip()
        if after_hours < 0 or after_hours <= previous:
            return {"valid": False, "reason": "escalation_hours_must_increase"}
        if not route:
            return {"valid": False, "reason": "route_required"}
        previous = after_hours
        normalized.append({"after_hours": after_hours, "route": route})
    return {"valid": True, "normalized": normalized}
