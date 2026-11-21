"""Shared controls for Financial Voucher and Opening Balance Entry source documents."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, update

from velora import db, get_list, throw
from velora.db.tables import get_table
from velora.permissions import get_session


def finance_settings():
    rows = get_list(
        "Finance Settings",
        fields=["name", "base_currency"],
        limit=1,
        ignore_permissions=True,
    )
    if not rows:
        throw("Complete Finance Settings before creating financial transactions.")
    return rows[0]


def decimal_amount(value, label):
    try:
        amount = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        throw(f"{label} must be a valid decimal amount.")
    if not amount.is_finite() or amount < 0:
        throw(f"{label} must be a finite, non-negative amount.")
    return amount


def calculate_totals(doc):
    debit = credit = Decimal("0")
    if not doc.lines or len(doc.lines) < 2:
        throw("At least two financial lines are required.")
    for index, line in enumerate(doc.lines, 1):
        d = decimal_amount(line.debit, f"Line {index} debit")
        c = decimal_amount(line.credit, f"Line {index} credit")
        if bool(d) == bool(c):
            throw(f"Line {index}: enter either a debit or a credit amount, but not both.")
        debit += d
        credit += c
    doc.total_debit = debit
    doc.total_credit = credit
    if debit != credit:
        throw(f"Financial voucher is not balanced. Debit {debit} does not equal credit {credit}.")
    if debit == 0:
        throw("A zero-value financial document cannot be submitted.")


def approval_required(doctype: str) -> bool:
    """True when an active approval workflow decides this document type. Finance Settings > Approvals can switch it off
    (the document is then approved on save); without a workflow and without a policy nothing waits for approval."""
    from velora import workflows
    return workflows.is_managed(doctype)


def approval_gap(doctype: str) -> bool:
    """Never blocks: a document type without an active workflow simply has no approval step (the gap is only shown in Finance Settings)."""
    return False


def _gap_message(doctype: str) -> str:
    return (f"Finance Settings require approval for {doctype}, but no approval workflow is active for it. "
            f"A System Manager can activate one under Settings > Workflows (or untick it under Finance Settings > Approvals).")


def settle_without_workflow(doc) -> bool:
    """A document type that has no approval workflow needs no approval: it counts as approved from the moment it is saved.

    Returns True when the document was settled this way. Rejected documents stay rejected."""
    if approval_required(doc.doctype) or approval_gap(doc.doctype):
        return False
    if str(doc.approval_status or "Pending") == "Pending":
        doc.approval_status = "Approved"
    return True


def is_approved(doctype: str, row) -> bool:
    """Has another document (a row or a document) been approved? Used when one document depends on another's approval."""
    get = row.get if isinstance(row, dict) else (lambda k, d=None: getattr(row, k, d))
    return get("approval_status") == "Approved" or (not approval_required(doctype) and not approval_gap(doctype) and get("approval_status") != "Rejected")


def validate_approval_transition(doc):
    """Keep the approval record honest. Who may approve is the workflow's business, not this code's.

    * No workflow for the document type: it is simply approved (nothing to wait for).
    * With a workflow, the status changes only through the workflow's own actions (the framework guards that);
      here the approver's identity and time are recorded and cannot be typed in.
    """
    status = str(doc.approval_status or "Pending")
    if status not in {"Pending", "Approved", "Rejected"}:
        throw("Invalid approval status.")
    old = getattr(doc, "_old", None) or {}
    if settle_without_workflow(doc):
        return
    if old and status != old.get("approval_status") and approval_gap(doc.doctype):
        throw(_gap_message(doc.doctype))
    if not old:
        if status != "Pending":
            throw("A new document starts as Pending; it is approved through its approval workflow.")
        if any(getattr(doc, field, None) for field in ("approved_by", "approved_on", "rejected_by", "rejected_on")):
            throw("Approval and rejection identity fields are system-controlled.")
        return
    session = get_session()
    if status == old.get("approval_status"):
        for field in ("approved_by", "approved_on", "rejected_by", "rejected_on"):
            if getattr(doc, field, None) != old.get(field):
                throw("Approval and rejection identity fields are system-controlled and cannot be changed.")
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if status == "Approved":
        doc.approved_by, doc.approved_on, doc.rejected_by, doc.rejected_on = session.user, now, None, None
    elif status == "Rejected":
        doc.rejected_by, doc.rejected_on, doc.approved_by, doc.approved_on = session.user, now, None, None
    else:
        doc.approved_by = doc.approved_on = doc.rejected_by = doc.rejected_on = None


def ensure_approved(doc, *, required=True):
    """Block use (submission, posting) of a document that is still waiting for, or was refused, its approval."""
    if not required:
        return
    if doc.approval_status == "Rejected":
        throw("A rejected document cannot be submitted. Reopen it through its approval workflow, correct it and obtain a new decision.")
    if settle_without_workflow(doc):
        return
    if approval_gap(doc.doctype):
        throw(_gap_message(doc.doctype))
    if doc.approval_status != "Approved":
        throw("This document is waiting for approval. It can be submitted once its approval workflow approves it.")


def posting_lines(doc):
    return [
        {
            "account": line.account,
            "debit": line.debit,
            "credit": line.credit,
            "party_type": line.party_type or None,
            "party": line.party or None,
            "cost_centre": line.cost_centre or None,
            "dimensions": line.dimensions or {},
            "line_description": line.line_description or doc.narration,
        }
        for line in doc.lines
    ]


def persist_posting_batch_link(doc, batch):
    """Persist the engine-generated link within the source document's submit transaction."""
    table = get_table(doc.doctype)
    db.conn().execute(update(table).where(table.c.name == doc.name).values(posting_batch=batch.name))
    doc.posting_batch = batch.name


def ensure_balance_sheet_accounts(doc):
    accounts = get_table("Account")
    groups = get_table("Account Group")
    with db.transaction() as conn:
        for index, line in enumerate(doc.lines, 1):
            row = conn.execute(
                select(groups.c.root_type)
                .select_from(accounts.join(groups, accounts.c.account_group == groups.c.name))
                .where(accounts.c.name == line.account)
                .limit(1)
            ).first()
            if not row:
                throw(f"Opening balance line {index}: Account {line.account!r} does not exist.")
            if row[0] not in {"Asset", "Liability", "Equity"}:
                throw(f"Opening balance line {index}: {line.account} is a {row[0]} account. Opening balances are restricted to Assets, Liabilities and Equity.")
