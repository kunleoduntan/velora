"""Administrator-configurable exception severity and routing policy."""
DEFAULTS = {
    "low_days": 1, "medium_days": 7, "high_days": 14, "critical_days": 30,
    "low_score": 0, "medium_score": 40, "high_score": 65, "critical_score": 85,
    "routes": {"Low": "", "Medium": "", "High": "", "Critical": ""},
    "evidence_required": True,
    "escalation_after_hours": "24,72,168",
    "escalation_targets": {},
}


def validate_exception_configuration(payload):
    p = dict(payload or {})
    errors = []
    day_keys = ("low_days", "medium_days", "high_days", "critical_days")
    score_keys = ("low_score", "medium_score", "high_score", "critical_score")
    normalized = dict(DEFAULTS)
    for key in day_keys + score_keys:
        try: normalized[key] = int(p.get(key, DEFAULTS[key]))
        except (TypeError, ValueError): errors.append(f"{key}_must_be_integer")
    if not errors:
        if not (0 <= normalized["low_days"] < normalized["medium_days"] < normalized["high_days"] < normalized["critical_days"]):
            errors.append("overdue_thresholds_must_increase")
        if not (0 <= normalized["low_score"] < normalized["medium_score"] < normalized["high_score"] < normalized["critical_score"] <= 100):
            errors.append("risk_score_thresholds_must_increase_within_0_100")
    routes = p.get("routes", DEFAULTS["routes"])
    if not isinstance(routes, dict): errors.append("routes_must_be_object")
    else:
        normalized["routes"] = {s: str(routes.get(s) or "").strip() for s in ("Low", "Medium", "High", "Critical")}
    normalized["evidence_required"] = bool(p.get("evidence_required", True))
    intervals = p.get("escalation_after_hours", DEFAULTS["escalation_after_hours"])
    interval_values = []
    try:
        interval_values = [int(x.strip()) for x in str(intervals).split(",") if x.strip()]
        if not interval_values or any(x <= 0 for x in interval_values) or interval_values != sorted(set(interval_values)):
            errors.append("escalation_intervals_must_be_positive_and_increasing")
        normalized["escalation_after_hours"] = ",".join(map(str, interval_values))
    except (TypeError, ValueError):
        errors.append("escalation_intervals_must_be_integers")
    targets = p.get("escalation_targets", DEFAULTS["escalation_targets"])
    if isinstance(targets, str):
        try:
            import json
            targets = json.loads(targets or "{}")
        except ValueError:
            errors.append("escalation_targets_must_be_json")
            targets = {}
    if not isinstance(targets, dict):
        errors.append("escalation_targets_must_be_object")
        targets = {}
    normalized_targets = {}
    for stage, users in targets.items():
        try: stage_no = int(stage)
        except (TypeError, ValueError): errors.append("escalation_stage_must_be_integer"); continue
        if stage_no < 1 or stage_no > len(interval_values if 'interval_values' in locals() else []):
            errors.append("escalation_stage_out_of_range"); continue
        if not isinstance(users, list):
            errors.append("escalation_stage_users_must_be_list"); continue
        clean = list(dict.fromkeys(str(u).strip() for u in users if str(u).strip()))
        normalized_targets[str(stage_no)] = clean
    normalized["escalation_targets"] = normalized_targets
    return {"valid": not errors, "errors": errors, "normalized": normalized}


def classify_with_configuration(*, due_date=None, today=None, risk_score=None, exception_type=None, configuration=None):
    from velora_governance.governance.services.governance_exception_centre import _as_date, SEVERITY_ORDER
    from datetime import date
    cfg = validate_exception_configuration(configuration or {})
    if not cfg["valid"]: raise ValueError("invalid_exception_configuration")
    c = cfg["normalized"]
    today = _as_date(today) if today else date.today()
    due = _as_date(due_date)
    overdue = max(0, (today - due).days) if due else 0
    if risk_score is not None:
        score = max(0, min(100, int(risk_score)))
        severity = "Critical" if score >= c["critical_score"] else "High" if score >= c["high_score"] else "Medium" if score >= c["medium_score"] else "Low"
    else:
        severity = "Critical" if overdue >= c["critical_days"] else "High" if overdue >= c["high_days"] else "Medium" if overdue >= c["medium_days"] else "Low"
    return {"severity": severity, "severity_rank": SEVERITY_ORDER[severity], "overdue_days": overdue,
            "risk_score": risk_score, "exception_type": str(exception_type or "Governance Exception")}


def validate_bulk_assignment(exception_names, user):
    names = list(dict.fromkeys(str(n).strip() for n in (exception_names or []) if str(n).strip()))
    user = str(user or "").strip()
    if not names: return {"valid": False, "reason": "exceptions_required"}
    if len(names) > 200: return {"valid": False, "reason": "bulk_limit_exceeded"}
    if not user: return {"valid": False, "reason": "user_required"}
    return {"valid": True, "names": names, "user": user}
