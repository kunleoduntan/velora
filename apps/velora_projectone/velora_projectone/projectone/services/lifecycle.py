"""Domain validation and controlled lifecycle transitions for ProjectOne."""
from decimal import Decimal, InvalidOperation
from datetime import date

PROJECT_STATES = {"Draft", "Proposed", "Under Review", "Approved", "Planning", "Active", "On Hold", "Completed", "Closed", "Cancelled"}
TRANSITIONS = {
    "Draft": {"Proposed", "Cancelled"},
    "Proposed": {"Under Review", "Draft", "Cancelled"},
    "Under Review": {"Approved", "Draft", "Cancelled"},
    "Approved": {"Planning", "On Hold", "Cancelled"},
    "Planning": {"Active", "On Hold", "Cancelled"},
    "Active": {"On Hold", "Completed"},
    "On Hold": {"Planning", "Active", "Cancelled"},
    "Completed": {"Closed"}, "Closed": set(), "Cancelled": set(),
}


def validate_project(data):
    required = ("title", "project_code", "project_manager")
    missing = [f for f in required if not str(data.get(f) or "").strip()]
    if missing:
        raise ValueError("Missing required project fields: " + ", ".join(missing))
    if data.get("start_date") and data.get("end_date"):
        start, end = date.fromisoformat(str(data["start_date"])), date.fromisoformat(str(data["end_date"]))
        if end < start:
            raise ValueError("Project end date cannot be earlier than start date.")
    progress = Decimal(str(data.get("progress_percent", 0)))
    if not progress.is_finite() or not Decimal("0") <= progress <= Decimal("100"):
        raise ValueError("Project progress must be between 0 and 100.")
    status = data.get("status", "Draft")
    if status not in PROJECT_STATES:
        raise ValueError(f"Unsupported project status: {status}")
    return True


def transition_project(current, target, evidence=None):
    if current not in PROJECT_STATES or target not in PROJECT_STATES:
        raise ValueError("Unknown project lifecycle state.")
    if target not in TRANSITIONS[current]:
        raise ValueError(f"Transition from {current} to {target} is not permitted.")
    evidence = evidence or {}
    if target == "Approved" and not evidence.get("approved_charter"):
        raise ValueError("An approved project charter is required before project approval.")
    if target == "Active" and not evidence.get("approved_baseline"):
        raise ValueError("An approved schedule baseline is required before activation.")
    if target == "Completed" and not evidence.get("accepted_deliverables"):
        raise ValueError("All required deliverables must be accepted before completion.")
    if target == "Closed":
        required = ("financial_reconciled", "commitments_cleared", "handover_accepted", "closure_approved")
        absent = [k for k in required if not evidence.get(k)]
        if absent:
            raise ValueError("Project closure requirements not met: " + ", ".join(absent))
    return {"from_status": current, "to_status": target, "requires_audit_event": True}


def validate_budget_revision(original, revised, approval_status):
    original, revised = Decimal(str(original)), Decimal(str(revised))
    if not original.is_finite() or not revised.is_finite() or min(original, revised) < 0:
        raise ValueError("Budget amounts must be finite and non-negative.")
    if revised != original and approval_status != "Approved":
        raise ValueError("A changed budget requires an approved budget revision.")
    return True


def validate_baseline_mutation(status):
    if status in {"Approved", "Superseded"}:
        raise ValueError("Approved baselines are immutable; create a new baseline version.")
    return True
