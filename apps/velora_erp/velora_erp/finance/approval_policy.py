"""The company's approval policy: which documents wait for approval.

Finance Settings > Approvals holds one row per approval document type. The policy only says *whether* approval is required;
*who* approves and in how many steps is the approval workflow's business (Settings > Workflows).

    ticked    -> the document waits for its workflow's approval; switching it on activates that workflow
                 (a sample is installed first when there is none)
    unticked  -> the document counts as approved as soon as it is saved; its workflow is switched off
    Switching a workflow on or off in the designer moves the policy row the same way, so the two never disagree.
    no row    -> no opinion: an active workflow, if any, applies

The framework asks `decide()` (hook `approval_policy_provider`) whenever it needs to know whether a workflow applies.
"""
from __future__ import annotations

from sqlalchemy import select


def _rows() -> dict[str, int]:
    from velora.db.tables import get_table
    table = get_table("Approval Policy Row")
    from velora import db
    with db.transaction() as c:
        found = c.execute(select(table.c.document_type, table.c.require_approval).where(table.c.parenttype == "Finance Settings")).all()
    return {r[0]: int(r[1] or 0) for r in found}


def decide(doctype: str):
    """True / False from the policy table, None when the document type has no row (or settings are not available yet)."""
    try:
        rows = _rows()
    except Exception:
        return None
    return bool(rows[doctype]) if doctype in rows else None


def workflow_changed(doctype: str, enabled: bool) -> None:
    """A workflow for `doctype` was switched on or off in the designer: the policy row follows, so settings and workflow never disagree."""
    from velora import db
    from velora.db.tables import get_table
    from sqlalchemy import update
    table = get_table("Approval Policy Row")
    with db.transaction() as c:
        c.execute(update(table).where(table.c.parenttype == "Finance Settings", table.c.document_type == doctype)
                  .values(require_approval=1 if enabled else 0))


def policy_doctypes() -> list[str]:
    from velora_erp.finance.workflow_templates import approval_doctypes
    return approval_doctypes()


def sync_rows(doc) -> None:
    """Make the policy table list exactly the approval document types: add the missing ones, drop unknown ones, merge duplicates.

    A new row starts ticked when an active workflow already enforces approval for that document, so opening this page
    never loosens an existing control."""
    from velora import workflows
    known = policy_doctypes()
    seen: dict[str, object] = {}
    for row in list(doc.approval_policy or []):
        name = (row.document_type or "").strip()
        if name in known and name not in seen:
            seen[name] = row
    doc.approval_policy = [seen[n] for n in known if n in seen]
    for name in known:
        if name not in seen:
            doc.append("approval_policy", {"document_type": name, "require_approval": 1 if workflows.has_enabled_workflow(name) else 0})
    doc._link_children()                                  # rows added during validation still need their parent, order and name


def apply(doc) -> list[str]:
    """After settings are saved: every ticked document gets an active workflow. Returns the workflows switched on."""
    from velora import workflows
    from velora_erp.finance import workflow_templates as wt
    on = []
    for row in doc.approval_policy or []:
        if not int(row.require_approval or 0):
            for name in workflows.enabled_names(row.document_type):       # unticked: its workflow goes back to being an inactive sample
                workflows.set_enabled(name, False)
            continue
        names = workflows.list_for_doctype(row.document_type)
        if not names:
            tpl = next((t for t in wt.templates() if t["doctype"] == row.document_type), None)
            if tpl is None:
                continue
            workflows.save_definition({**tpl, "enabled": True}, system=True)
            on.append(tpl["name"])
        elif not workflows.has_enabled_workflow(row.document_type):
            workflows.set_enabled(names[0], True)
            on.append(names[0])
    return on
