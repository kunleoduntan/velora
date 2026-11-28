"""Project governance, document control and benefits calculations.

Pure validation/calculation functions. Durable approvals, document storage and
workflow evidence remain owned by injected Velora host services.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def _number(value, field):
    try:
        result = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric.")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result


def evaluate_stage_gate(criteria: list, evidence: dict, *, waiver_reason: str | None = None) -> dict:
    """Evaluate a gate against explicit criteria IDs and evidence references."""
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("At least one stage-gate criterion is required.")
    if not isinstance(evidence, dict):
        raise ValueError("Evidence must be an object keyed by criterion ID.")
    missing = []
    satisfied = []
    for item in criteria:
        if not isinstance(item, dict) or not item.get("id") or not item.get("description"):
            raise ValueError("Each criterion requires an id and description.")
        cid = str(item["id"])
        supplied = evidence.get(cid)
        if supplied is True or (isinstance(supplied, str) and supplied.strip()):
            satisfied.append(cid)
        elif isinstance(supplied, dict) and any(str(v).strip() for v in supplied.values() if v is not None):
            satisfied.append(cid)
        else:
            missing.append(cid)
    waived = bool(waiver_reason and waiver_reason.strip())
    passed = not missing or waived
    return {"passed": passed, "status": "Passed" if passed else "Failed",
            "satisfied_criteria": satisfied, "missing_criteria": missing,
            "waived": waived, "waiver_reason": waiver_reason if waived else None,
            "requires_independent_approval": True}


def assess_change_impact(*, schedule_days=0, cost_delta=0, scope_change=False,
                         risk_change=False, quality_change=False,
                         thresholds: dict | None = None) -> dict:
    """Classify change impact using company-configurable escalation thresholds."""
    thresholds = thresholds or {}
    max_days = _number(thresholds.get("schedule_days", 10), "threshold.schedule_days")
    max_cost = abs(_number(thresholds.get("cost_delta", 100000), "threshold.cost_delta"))
    days = _number(schedule_days, "schedule_days")
    cost = _number(cost_delta, "cost_delta")
    if max_days < 0:
        raise ValueError("Schedule threshold cannot be negative.")
    drivers = []
    if abs(days) > max_days: drivers.append("Schedule")
    if abs(cost) > max_cost: drivers.append("Cost")
    if scope_change: drivers.append("Scope")
    if risk_change: drivers.append("Risk")
    if quality_change: drivers.append("Quality")
    level = "Major" if len(drivers) >= 2 or any(x in drivers for x in ("Scope", "Quality")) else ("Moderate" if drivers else "Minor")
    return {"impact_level": level, "impact_drivers": drivers,
            "schedule_delta_days": float(days), "cost_delta": float(cost),
            "requires_change_board": level == "Major",
            "requires_baseline_revision": bool(drivers),
            "approval_required": True}


def validate_document_revision(*, current_version, proposed_version, file_reference,
                               approval_status="Draft", classification="Internal") -> dict:
    """Validate sequential, traceable document revisions before host persistence."""
    current = int(current_version or 0)
    proposed = int(proposed_version)
    if current < 0 or proposed < 1:
        raise ValueError("Document versions must be positive integers (current may be zero).")
    if proposed != current + 1:
        raise ValueError("A new document revision must increment the current version by exactly one.")
    if not isinstance(file_reference, str) or not file_reference.strip():
        raise ValueError("A controlled file reference is required.")
    if approval_status not in {"Draft", "Pending Approval", "Approved", "Superseded"}:
        raise ValueError("Unsupported document approval status.")
    if classification not in {"Public", "Internal", "Confidential", "Restricted"}:
        raise ValueError("Unsupported document classification.")
    return {"valid": True, "version": proposed, "supersedes_version": current or None,
            "approval_status": "Draft", "classification": classification,
            "requires_approval": True, "immutable_after_approval": True}


def evaluate_closure_checklist(checklist: dict, *, lessons_learned: str = "",
                               benefits_owner: str | None = None) -> dict:
    required = ("deliverables_accepted", "financial_reconciled", "commitments_cleared", "assets_handed_over")
    if not isinstance(checklist, dict):
        raise ValueError("Closure checklist must be an object.")
    incomplete = [key for key in required if checklist.get(key) not in (True, 1, "1")]
    missing_evidence = []
    if not str(lessons_learned or "").strip(): missing_evidence.append("lessons_learned")
    if not str(benefits_owner or "").strip(): missing_evidence.append("benefits_owner")
    return {"ready_for_approval": not incomplete and not missing_evidence,
            "incomplete_controls": incomplete, "missing_evidence": missing_evidence,
            "requires_independent_approval": True}


def calculate_benefit_realisation(*, baseline_value=0, target_value, actual_value) -> dict:
    baseline = _number(baseline_value, "baseline_value")
    target = _number(target_value, "target_value")
    actual = _number(actual_value, "actual_value")
    if target == baseline:
        progress = 100.0 if actual == target else 0.0
    else:
        progress = float((actual - baseline) / (target - baseline) * 100)
    return {"baseline_value": float(baseline), "target_value": float(target),
            "actual_value": float(actual), "realisation_percent": round(progress, 2),
            "remaining_to_target": float(target - actual),
            "target_achieved": actual >= target if target >= baseline else actual <= target}
