"""Sample approval workflows to learn from. They are offered switched off and nothing in the code depends on them.

VeloraERP never hard-codes an approval rule: each company draws its own in Settings > Workflows. These samples show one sensible shape
(Pending, Approved, Rejected, with a different person approving) for documents that move stock or money but have no approval field yet.
Open one, change the roles and states to fit your control, add the state field it names, and only then switch it on.
They are offered through the framework's starter-workflow list (Settings > Workflows) and installed only when a System Manager asks, still switched off."""
from __future__ import annotations

# document type -> (state field to use, how to get it, roles that approve)
SAMPLES = {
    "Stock Entry": ("entry_status", "Uses the existing Entry Status field (Draft, Pending Approval, Approved, Rejected).", ["Finance Manager"]),
    "Purchase Receipt": ("workflow_state", "Uses the built-in Workflow State field: nothing to customise.", ["Finance Manager"]),
    "Delivery Note": ("workflow_state", "Uses the built-in Workflow State field: nothing to customise.", ["Finance Manager"]),
    "Sales Order": ("workflow_state", "Uses the built-in Workflow State field: nothing to customise.", ["Finance Manager"]),
    "Purchase Order": ("workflow_state", "Uses the built-in Workflow State field: nothing to customise.", ["Finance Manager"]),
    "Salary Slip": ("workflow_state", "Uses the built-in Workflow State field: nothing to customise.", ["Finance Manager"]),
}


def sample_name(doctype: str) -> str:
    return f"SAMPLE (off) - {doctype} Approval"


def definition(doctype: str) -> dict:
    field, _how, roles = SAMPLES[doctype]
    pending, approved, rejected = ("Pending Approval", "Approved", "Rejected") if doctype == "Stock Entry" else ("Pending", "Approved", "Rejected")
    start = "Draft" if doctype == "Stock Entry" else pending
    def tr(action, a, b, who=True):
        return {"action": action, "label": action, "from_state": a, "to_state": b, "roles": list(roles), "users": [], "approval_mode": "single",
                "required_approvals": 1, "prevent_self_approval": action in ("Approve", "Reject")}
    states = ([{"name": "Draft"}] if start == "Draft" else []) + [{"name": pending}, {"name": approved, "allows_submit": True, "locks_content": True}, {"name": rejected}]
    transitions = ([tr("Send for approval", "Draft", pending)] if start == "Draft" else []) + [
        tr("Approve", pending, approved), tr("Reject", pending, rejected), tr("Reopen", approved, pending), tr("Reopen for correction", rejected, pending)]
    return {"name": sample_name(doctype), "doctype": doctype, "initial_state": start, "states": states, "transitions": transitions, "state_field": field, "enabled": False}
