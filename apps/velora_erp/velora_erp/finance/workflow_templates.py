"""Starter approval workflows for finance and payroll documents.

No approval rule lives in the finance code. These are ordinary workflow definitions, installed inactive as samples, that a company
reviews, edits or replaces in the workflow designer (Settings > Workflows), because who approves what differs by company.
Finance Settings > Approvals decides which documents need approval; a document that does not is approved as soon as it is saved.

Every definition follows the same shape so it is easy to read and change:
    Pending --Approve--> Approved (may be submitted; content locked)      Approver cannot be the maker
    Pending --Reject---> Rejected                                         Approver cannot be the maker
    Approved/Rejected --Reopen--> Pending                                 for correction and a fresh decision
"""
from __future__ import annotations

FINANCE_APPROVERS = ["Finance Manager", "System Manager"]
PAYROLL_APPROVERS = ["Payroll Manager", "Finance Manager", "System Manager"]
HR_FINANCE_APPROVERS = ["Payroll Manager", "Finance Manager", "System Manager"]

PAYROLL_DOCTYPES = {
    "Payroll Input", "Payroll Run", "Payroll Payment", "Payroll Tax Rule", "Salary Structure", "Salary Structure Assignment",
    "Employee Loan", "Employee Loan Application", "Employee Loan Repayment", "Employee Loan Type", "Employee Advance",
    "Employee Advance Settlement", "Employee Tax Profile",
}
# approval_status documents that are not "financial documents" but follow the same Pending/Approved/Rejected model
EXTRA = {"Tax Refund Credit Review": PAYROLL_APPROVERS}


def _definition(doctype: str, approvers: list[str]) -> dict:
    t = lambda action, a, b, roles, **kw: {"action": action, "label": action, "from_state": a, "to_state": b, "roles": roles, "users": [], "approval_mode": "single", "required_approvals": 1, **kw}
    return {
        "name": f"{doctype} Approval", "doctype": doctype, "initial_state": "Pending", "state_field": "approval_status",
        "states": [{"name": "Pending", "x": 70, "y": 80}, {"name": "Approved", "allows_submit": True, "locks_content": True, "x": 370, "y": 20},
                   {"name": "Rejected", "x": 370, "y": 170}],
        "transitions": [t("Approve", "Pending", "Approved", approvers, prevent_self_approval=True),
                        t("Reject", "Pending", "Rejected", approvers, prevent_self_approval=True),
                        t("Reopen", "Approved", "Pending", approvers), t("Reopen for correction", "Rejected", "Pending", approvers)],
    }


def approval_doctypes() -> list[str]:
    """Every finance or payroll document type that carries the Pending/Approved/Rejected approval field."""
    from velora.meta.registry import registry
    names = []
    for meta in registry.all():
        name = meta.name
        f = meta.get_field("approval_status")
        if f is not None and list(f.choices or []) == ["Pending", "Approved", "Rejected"] and getattr(meta, "is_submittable", False):
            names.append(name)
    return sorted(set(names) | set(EXTRA))


def templates() -> list[dict]:
    out = []
    for doctype in approval_doctypes():
        approvers = PAYROLL_APPROVERS if (doctype in PAYROLL_DOCTYPES or doctype in EXTRA) else FINANCE_APPROVERS
        out.append(_definition(doctype, approvers))
    return out


def install_missing(enabled: bool = False) -> list[str]:
    """Install the sample workflow for every approval document type that has none.

    New companies get them inactive: they are samples to look at, edit and switch on (Finance Settings > Approvals does both
    in one step). An upgrading company passes enabled=True so approvals that used to be enforced stay enforced."""
    from velora import workflows
    done = []
    for tpl in templates():
        if workflows.list_for_doctype(tpl["doctype"]): continue
        workflows.save_definition({**tpl, "enabled": bool(enabled)}, system=True); done.append(tpl["name"])
    return done
