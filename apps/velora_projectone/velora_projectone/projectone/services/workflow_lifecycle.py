"""Fail-closed lifecycle policy validation for native ProjectOne workflow commands.

This module validates intent and current state. The injected Velora workflow
service remains authoritative for transition execution, persistence and audit.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LifecyclePolicy:
    state_field: str
    transitions: dict[str, frozenset[str]]
    approval_actions: frozenset[str] = frozenset()
    require_evidence: frozenset[str] = frozenset()


COMMON = {
    "submit_for_approval": frozenset({"Draft"}),
    "start": frozenset({"Open"}),
    "hold": frozenset({"Open", "In Progress"}),
    "resume": frozenset({"On Hold"}),
    "complete": frozenset({"In Progress", "Open"}),
    "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
}

POLICIES: dict[str, LifecyclePolicy] = {
    "Project": LifecyclePolicy("status", {
        **{k: v for k, v in COMMON.items() if k != "submit_for_approval"}, "approve": frozenset({"Draft"}),
        "suspend": frozenset({"Open", "In Progress"}),
        "close": frozenset({"Completed"}),
    }, frozenset({"approve"}), frozenset({"approve", "close"})),
    "Project Portfolio": LifecyclePolicy("status", {
        **{k: v for k, v in COMMON.items() if k != "submit_for_approval"}, "approve": frozenset({"Draft"}),
        "close": frozenset({"Completed"}),
    }, frozenset({"approve"}), frozenset({"approve", "close"})),
    "Project Programme": LifecyclePolicy("status", {
        **{k: v for k, v in COMMON.items() if k != "submit_for_approval"}, "approve": frozenset({"Draft"}),
        "close": frozenset({"Completed"}),
    }, frozenset({"approve"}), frozenset({"approve", "close"})),
    "Project Baseline": LifecyclePolicy("approval_status", {
        "submit_for_approval": frozenset({"Draft"}),
        "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
        "supersede": frozenset({"Approved"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Change Request": LifecyclePolicy("approval_status", {
        "submit_for_approval": frozenset({"Draft"}),
        "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
        "withdraw": frozenset({"Draft", "Pending Approval"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Task": LifecyclePolicy("status", {
        "start": frozenset({"Open"}), "hold": frozenset({"Open", "In Progress"}),
        "resume": frozenset({"On Hold"}), "complete": frozenset({"In Progress"}),
        "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
    }, require_evidence=frozenset({"complete"})),
    "Project Milestone": LifecyclePolicy("status", {
        "start": frozenset({"Open"}), "hold": frozenset({"Open", "In Progress"}),
        "resume": frozenset({"On Hold"}), "submit_for_acceptance": frozenset({"In Progress"}),
        "accept": frozenset({"In Progress"}), "reject": frozenset({"In Progress"}),
        "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
    }, frozenset({"accept", "reject"}), frozenset({"submit_for_acceptance", "accept"})),
    "Project Deliverable": LifecyclePolicy("status", {
        "start": frozenset({"Open"}), "submit_for_acceptance": frozenset({"In Progress"}),
        "accept": frozenset({"In Progress"}), "reject": frozenset({"In Progress"}),
        "hold": frozenset({"Open", "In Progress"}), "resume": frozenset({"On Hold"}),
        "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
    }, frozenset({"accept", "reject"}), frozenset({"submit_for_acceptance", "accept"})),
    "Project Risk": LifecyclePolicy("status", {
        "review": frozenset({"Draft", "Open"}), "escalate": frozenset({"Open", "In Progress"}),
        "mitigate": frozenset({"Open", "In Progress"}), "hold": frozenset({"Open", "In Progress"}),
        "resume": frozenset({"On Hold"}), "close": frozenset({"In Progress"}),
        "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
    }, require_evidence=frozenset({"escalate", "close"})),
    "Project Charter": LifecyclePolicy("approval_status", {
        "submit_for_approval": frozenset({"Draft"}), "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Business Case": LifecyclePolicy("approval_status", {
        "submit_for_approval": frozenset({"Draft"}), "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Document Register": LifecyclePolicy("approval_status", {
        "submit_for_approval": frozenset({"Draft"}), "approve": frozenset({"Pending Approval"}),
        "supersede": frozenset({"Approved"}),
    }, frozenset({"approve"}), frozenset({"approve"})),
    "Project Closure": LifecyclePolicy("closure_approval", {
        "submit_for_approval": frozenset({"Draft"}), "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Stage Gate": LifecyclePolicy("gate_status", {
        "submit_for_approval": frozenset({"Draft"}), "pass": frozenset({"Pending Approval"}),
        "fail": frozenset({"Pending Approval"}), "waive": frozenset({"Pending Approval"}),
    }, frozenset({"pass", "fail", "waive"}), frozenset({"pass", "fail", "waive"})),
    "Project Performance Obligation": LifecyclePolicy("status", {
        "submit_for_approval": frozenset({"Draft"}),
        "approve": frozenset({"Pending Approval"}),
        "reject": frozenset({"Pending Approval"}),
        "suspend": frozenset({"Approved"}),
        "resume": frozenset({"Suspended"}),
        "complete": frozenset({"Approved", "Suspended"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Revenue Recognition": LifecyclePolicy("approval_status", {
        "approve": frozenset({"Pending Review"}),
        "reject": frozenset({"Pending Review"}),
        "supersede": frozenset({"Approved"}),
    }, frozenset({"approve", "reject"}), frozenset({"approve", "reject"})),
    "Project Issue": LifecyclePolicy("status", {
        "start": frozenset({"Open"}), "escalate": frozenset({"Open", "In Progress"}),
        "resolve": frozenset({"In Progress"}), "close": frozenset({"In Progress"}),
        "hold": frozenset({"Open", "In Progress"}), "resume": frozenset({"On Hold"}),
        "cancel": frozenset({"Draft", "Open", "In Progress", "On Hold"}),
    }, require_evidence=frozenset({"escalate", "resolve", "close"})),
}


def validate_lifecycle_command(doctype: str, action: str, document: dict,
                               actor_id: str, evidence: dict | None = None) -> dict:
    """Validate a requested command without mutating the source document."""
    policy = POLICIES.get(doctype)
    if policy is None:
        raise ValueError("Workflow is not enabled for this DocType.")
    if action not in policy.transitions:
        raise ValueError(f"Action '{action}' is not enabled for {doctype}.")
    state = document.get(policy.state_field)
    if state not in policy.transitions[action]:
        raise ValueError(f"Action '{action}' is not valid from state '{state}'.")
    evidence = evidence or {}
    if not isinstance(evidence, dict):
        raise ValueError("Workflow evidence must be an object.")
    if action in policy.require_evidence and not evidence:
        raise ValueError(f"Action '{action}' requires supporting evidence.")
    if doctype in {"Project Performance Obligation", "Project Revenue Recognition"}:
        if action == "approve" and not (evidence.get("approval_reference") or evidence.get("finance_review_reference")):
            raise ValueError("Finance approval requires an approval or finance review reference.")
        if action == "reject" and not str(evidence.get("reason") or "").strip():
            raise ValueError("Finance rejection requires a documented reason.")
    if action in policy.approval_actions:
        creator = document.get("owner") or document.get("created_by") or document.get("requested_by")
        if creator and creator == actor_id:
            raise PermissionError("Maker-checker control: the requester cannot approve or reject their own submission.")
    return {"doctype": doctype, "action": action, "state_field": policy.state_field,
            "current_state": state, "validated": True}
