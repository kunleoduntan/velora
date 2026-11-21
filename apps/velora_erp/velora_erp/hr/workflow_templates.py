"""Sample approval workflows for HR documents, installed (inactive) as ordinary GUI-editable workflow definitions.

Approval is never decided in controller code. These definitions are plain data in the company's workflow
designer: change who approves, add steps, add conditions (for example "more than 10 days") or turn a
workflow off from the GUI. Installing is idempotent and never overwrites a definition that already exists.
"""
from __future__ import annotations

MANAGERS = ["HR Manager", "System Manager"]


def _simple(doctype, field, approvers, *, initial="Draft"):
    states = [{"name": "Draft"}, {"name": "Pending Approval"}, {"name": "Approved", "is_final": True, "allows_submit": True}, {"name": "Rejected"}]
    transitions = [
        {"action": "Submit for Approval", "from_state": "Draft", "to_state": "Pending Approval", "roles": [], "anyone": True},
        {"action": "Approve", "from_state": "Pending Approval", "to_state": "Approved", "roles": approvers, "prevent_self_approval": True},
        {"action": "Reject", "from_state": "Pending Approval", "to_state": "Rejected", "roles": approvers, "prevent_self_approval": True},
        {"action": "Reopen", "from_state": "Rejected", "to_state": "Draft", "roles": [], "anyone": True},
    ]
    return {"name": f"{doctype} Approval", "doctype": doctype, "initial_state": initial, "state_field": field, "states": states, "transitions": transitions}


def _separation():
    names = ["Draft", "Submitted", "Under Review", "Approved", "Rejected", "Clearance In Progress", "Cleared", "Closed"]
    states = [{"name": n, "is_final": n in ("Closed", "Rejected")} for n in names]
    hr = MANAGERS
    t = lambda a, f, to, roles=hr, **k: {"action": a, "from_state": f, "to_state": to, "roles": roles, **k}
    transitions = [t("Submit", "Draft", "Submitted", [], anyone=True), t("Start Review", "Submitted", "Under Review"),
                   t("Approve", "Under Review", "Approved", prevent_self_approval=True), t("Reject", "Under Review", "Rejected", prevent_self_approval=True),
                   t("Begin Clearance", "Approved", "Clearance In Progress"), t("Complete Clearance", "Clearance In Progress", "Cleared"),
                   t("Close Separation", "Cleared", "Closed")]
    return {"name": "Employee Separation Approval", "doctype": "Employee Separation", "initial_state": "Draft", "state_field": "workflow_status", "states": states, "transitions": transitions}


def _review():
    names = ["Draft", "Manager Review", "HR Review", "Pending Approval", "Approved", "Acknowledged", "Closed", "Returned"]
    states = [{"name": n, "is_final": n == "Closed"} for n in names]
    t = lambda a, f, to, roles, **k: {"action": a, "from_state": f, "to_state": to, "roles": roles, **k}
    mgr = ["Department Manager", "HR Manager", "System Manager"]
    transitions = [t("Send to Manager", "Draft", "Manager Review", [], anyone=True), t("Send to HR", "Manager Review", "HR Review", mgr),
                   t("Request Approval", "HR Review", "Pending Approval", MANAGERS), t("Approve", "Pending Approval", "Approved", MANAGERS, prevent_self_approval=True),
                   t("Return", "Pending Approval", "Returned", MANAGERS), t("Reopen", "Returned", "Draft", MANAGERS),
                   t("Acknowledge", "Approved", "Acknowledged", [], anyone=True), t("Close", "Acknowledged", "Closed", MANAGERS)]
    return {"name": "Performance Review Approval", "doctype": "Performance Review", "initial_state": "Draft", "state_field": "review_status", "states": states, "transitions": transitions}


def templates() -> list[dict]:
    mgr = ["Department Manager", "HR Manager", "System Manager"]
    return [
        _simple("Leave Application", "workflow_status", mgr), _simple("Leave Allocation", "allocation_status", MANAGERS),
        _simple("Overtime Request", "approval_status", mgr), _simple("Attendance", "approval_status", mgr),
        _simple("Job Requisition", "requisition_status", MANAGERS), _simple("Job Offer", "approval_status", MANAGERS),
        _simple("Probation Review", "approval_status", MANAGERS), _simple("Employee Change Request", "request_status", MANAGERS),
        _simple("Shift Assignment", "assignment_status", MANAGERS), _simple("Employee Status History", "approval_status", MANAGERS),
        _simple("Employment Contract", "contract_status", MANAGERS), _simple("Reporting Assignment", "assignment_status", MANAGERS),
        _simple("Training Program", "approval_status", MANAGERS),
        _simple("Department Staff Budget", "budget_status", ["Finance Manager", "HR Manager", "System Manager"]),
        _simple("Material Request", "request_status", ["Inventory Manager", "Department Manager", "Finance Manager", "System Manager"]),
        _simple("Stock Entry", "entry_status", ["Inventory Manager", "Finance Manager", "System Manager"]), _separation(), _review(),
    ]


def install_templates(doctypes: list[str] | None = None, enabled: bool = False, system: bool = False) -> dict:
    """Create the sample workflows that do not exist yet, inactive unless asked otherwise.

    They are samples to read, edit and switch on in Settings > Workflows. Requires a System Manager (enforced by the workflow
    engine) unless the app itself is installing them (`system=True`)."""
    from velora import workflows
    workflows.ensure()
    existing = {d["name"] for d in workflows.list_definitions()}
    created, skipped = [], []
    for tpl in templates():
        if doctypes and tpl["doctype"] not in doctypes: continue
        if tpl["name"] in existing: skipped.append(tpl["name"]); continue
        workflows.save_definition({**tpl, "enabled": bool(enabled)}, system=system); created.append(tpl["name"])
    return {"created": created, "skipped": skipped}
