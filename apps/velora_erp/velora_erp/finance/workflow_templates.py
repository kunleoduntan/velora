"""Workflow policy discovery only.

VeloraERP installs no workflow by itself. Companies create and maintain every workflow through Settings > Workflows;
the sample starters below are only offered there and are never switched on. The one helper
below discovers approval-capable DocTypes from metadata for Finance Settings;
it does not prescribe states, roles, transitions or approvers.
"""
from __future__ import annotations


def approval_doctypes() -> list[str]:
    from velora.meta.registry import registry
    names = []
    for meta in registry.all():
        field = meta.get_field("approval_status")
        if field is not None and list(field.choices or []) == ["Pending", "Approved", "Rejected"] and getattr(meta, "is_submittable", False):
            names.append(meta.name)
    return sorted(set(names))


def _definition(doctype: str, approvers: list[str]) -> dict:
    """Generic test/example definition; never installed or registered as a template."""
    def transition(action, source, target):
        return {"action": action, "label": action, "from_state": source, "to_state": target,
                "roles": list(approvers), "users": [], "approval_mode": "single", "required_approvals": 1,
                "prevent_self_approval": action in ("Approve", "Reject")}
    return {"name": f"{doctype} Approval", "doctype": doctype, "initial_state": "Pending", "state_field": "approval_status",
            "states": [{"name": "Pending"}, {"name": "Approved", "allows_submit": True, "locks_content": True}, {"name": "Rejected"}],
            "transitions": [transition("Approve", "Pending", "Approved"), transition("Reject", "Pending", "Rejected"),
                            transition("Reopen", "Approved", "Pending"), transition("Reopen for correction", "Rejected", "Pending")]}


def templates() -> list[dict]:
    """Sample workflows to learn from (hook `workflow_template_provider`). They are only offered: installing one saves it switched off, and nothing depends on it."""
    from velora_erp.finance.workflow_samples import SAMPLES, definition
    return [definition(d) for d in SAMPLES]


def install_missing(enabled: bool = False) -> list[str]:
    """Retained for upgrade compatibility; intentionally creates no workflows."""
    return []
