"""Canonical financial reporting adapter for the VeloraERP Account Ledger.

The framework report designer consumes this contract instead of assuming a
legacy GL Entry schema. All amounts returned are company-base-currency amounts.
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from velora import db
from velora.db.tables import get_table
from velora.exceptions import PermissionDenied
from velora.permissions import check_permission, field_access


def check_access():
    """Enforce metadata and field-level access before financial data is read."""
    from velora import registry
    required = {
        "Account": ("name", "account_code", "account_name", "account_group", "disabled"),
        "Account Group": ("name", "root_type", "is_group", "disabled"),
        "Account Ledger Record": (
            "name", "posting_date", "account", "base_debit", "base_credit",
            "source_doctype", "source_name", "party_type", "party",
            "line_description", "posting_event", "cost_centre", "dimensions", "business_unit", "branch", "project",
        ),
    }
    for doctype in required:
        check_permission(registry.get(doctype), "read")
    for doctype, fields in required.items():
        hidden = [field for field in fields if field_access(doctype, field) == "hidden"]
        if hidden:
            raise PermissionDenied(
                f"Financial reporting requires read access to {doctype} field(s): {', '.join(hidden)}"
            )


def get_accounts():
    """Return canonical account rows expected by the framework statement engine."""
    account = get_table("Account")
    group = get_table("Account Group")
    query = select(
        account.c.name.label("name"),
        account.c.account_code.label("account_number"),
        group.c.root_type.label("root_type"),
        group.c.is_group.label("group_is_group"),
        account.c.disabled.label("account_disabled"),
        group.c.disabled.label("group_disabled"),
    ).select_from(account.join(group, account.c.account_group == group.c.name))
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(query).mappings().all()]
    return [
        {
            "name": r["name"],
            "account_number": r["account_number"],
            "root_type": r["root_type"],
            # Account is always a posting-level leaf; grouping lives in Account Group.
            "is_group": False,
            "disabled": bool(r["account_disabled"] or r["group_disabled"]),
        }
        for r in rows
    ]


def _dimension_conditions(ledger, dimensions):
    """Build allow-listed ledger-dimension predicates without interpolating SQL identifiers."""
    conditions = []
    direct = {"cost_centre", "business_unit", "branch", "project"}
    for key, value in (dimensions or {}).items():
        if key in direct and key in ledger.c:
            conditions.append(ledger.c[key] == value)
        elif "dimensions" in ledger.c:
            # Dimension codes are configurable and often uppercase. Department is a
            # standard report alias, so match its canonical case variants explicitly.
            keys = ("department", "DEPARTMENT", "Department") if key == "department" else (key,)
            conditions.append(or_(*(ledger.c.dimensions[item].as_string() == value for item in keys)))
        else:
            raise ValueError(f"Ledger dimension {key!r} is not available in this reporting provider")
    return conditions


def get_account_totals(account_names, start_date, end_date, *, balance_at_date=False, dimensions=None):
    """Return account-level base-currency debit/credit totals for a statement column."""
    if not account_names:
        return []
    ledger = get_table("Account Ledger Record")
    conditions = [ledger.c.account.in_(list(account_names)), ledger.c.posting_date <= end_date]
    conditions.extend(_dimension_conditions(ledger, dimensions))
    if not balance_at_date:
        conditions.append(ledger.c.posting_date >= start_date)
    query = select(
        ledger.c.account.label("account"),
        func.coalesce(func.sum(ledger.c.base_debit), 0).label("debit"),
        func.coalesce(func.sum(ledger.c.base_credit), 0).label("credit"),
    ).where(and_(*conditions)).group_by(ledger.c.account)
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(query).mappings().all()]


def get_ledger_entries(account_names, start_date, end_date, limit, *, balance_at_date=False, dimensions=None):
    """Return canonical transaction detail for statement-cell drill-down."""
    if not account_names:
        return []
    ledger = get_table("Account Ledger Record")
    conditions = [ledger.c.account.in_(list(account_names)), ledger.c.posting_date <= end_date]
    conditions.extend(_dimension_conditions(ledger, dimensions))
    if not balance_at_date:
        conditions.append(ledger.c.posting_date >= start_date)
    query = select(ledger).where(and_(*conditions)).order_by(
        ledger.c.posting_date, ledger.c.creation, ledger.c.name
    ).limit(max(1, min(int(limit), 1000)))
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(query).mappings().all()]
    return [
        {
            "name": r["name"],
            "posting_date": r["posting_date"],
            "account": r["account"],
            "voucher_type": r["source_doctype"],
            "voucher_no": r["source_name"],
            "party_type": r.get("party_type"),
            "party": r.get("party"),
            "remarks": r.get("line_description"),
            "debit": r.get("base_debit") or 0,
            "credit": r.get("base_credit") or 0,
            "is_reversal": False,
            "is_cancelled": False,
        }
        for r in rows
    ]


def get_budget_totals(account_names, start_date, end_date, *, budget_name, dimensions=None):
    """Return approved budget allocations prorated over the selected date window."""
    from datetime import date
    from decimal import Decimal
    from velora.exceptions import ValidationError
    from velora.permissions import check_permission, field_access
    from velora import registry
    if not budget_name:
        raise ValidationError("Select a Budget Name to run a budget-versus-actual report.")
    if not account_names:
        return []
    check_permission(registry.get("Financial Budget"), "read")
    for doctype, fields in {
        "Financial Budget": ("name", "budget_name", "docstatus", "approval_status", "budget_status"),
        "Financial Budget Line": ("parent", "account", "period_start", "period_end", "budget_amount", "cost_centre", "branch", "business_unit", "project", "department", "dimensions"),
    }.items():
        hidden = [field for field in fields if field_access(doctype, field) == "hidden"]
        if hidden:
            raise PermissionDenied(f"Budget reporting requires read access to {doctype} field(s): {', '.join(hidden)}")
    parent = get_table("Financial Budget")
    line = get_table("Financial Budget Line")
    with db.transaction() as conn:
        active_budget = conn.execute(
            select(parent.c.name).where(
                parent.c.budget_name == budget_name,
                parent.c.docstatus == 1,
                parent.c.approval_status == "Approved",
                parent.c.budget_status == "Active",
            ).limit(1)
        ).scalar_one_or_none()
    if not active_budget:
        raise ValidationError(f"Budget {budget_name!r} is not an active, independently approved and submitted budget.")
    conditions = [
        parent.c.budget_name == budget_name,
        parent.c.docstatus == 1,
        parent.c.approval_status == "Approved",
        parent.c.budget_status == "Active",
        line.c.account.in_(list(account_names)),
        line.c.period_start <= end_date,
        line.c.period_end >= start_date,
    ]
    direct = {"cost_centre", "branch", "business_unit", "project", "department"}
    for key, value in (dimensions or {}).items():
        if key in direct and key in line.c:
            conditions.append(line.c[key] == value)
        elif "dimensions" in line.c:
            keys = ("department", "DEPARTMENT", "Department") if key == "department" else (key,)
            conditions.append(or_(*(line.c.dimensions[item].as_string() == value for item in keys)))
        else:
            raise ValidationError(f"Budget line dimension {key!r} is not supported.")
    query = select(
        line.c.account.label("account"), line.c.period_start.label("period_start"),
        line.c.period_end.label("period_end"), line.c.budget_amount.label("budget_amount"),
    ).select_from(line.join(parent, line.c.parent == parent.c.name)).where(and_(*conditions))
    with db.transaction() as conn:
        rows = [dict(row) for row in conn.execute(query).mappings().all()]
        # Approved Budget Adjustments (increase / decrease / transfer) are layered on the approved budget.
        adj, adj_line = get_table("Budget Adjustment"), get_table("Budget Adjustment Line")
        adj_conditions = [
            adj.c.financial_budget == active_budget, adj.c.docstatus == 1, adj.c.approval_status == "Approved",
            adj_line.c.account.in_(list(account_names)), adj_line.c.period_start <= end_date, adj_line.c.period_end >= start_date,
        ]
        for key, value in (dimensions or {}).items():
            if key in direct and key in adj_line.c:
                adj_conditions.append(adj_line.c[key] == value)
            else:
                adj_conditions = None   # adjustments carry no free-form dimensions; skip them for such filters
                break
        if adj_conditions is not None:
            rows += [dict(row) for row in conn.execute(
                select(adj_line.c.account.label("account"), adj_line.c.period_start.label("period_start"),
                       adj_line.c.period_end.label("period_end"), adj_line.c.change_amount.label("budget_amount"))
                .select_from(adj_line.join(adj, adj_line.c.parent == adj.c.name)).where(and_(*adj_conditions))).mappings().all()]
    totals = {}
    for row in rows:
        period_start = row["period_start"] if isinstance(row["period_start"], date) else date.fromisoformat(str(row["period_start"])[:10])
        period_end = row["period_end"] if isinstance(row["period_end"], date) else date.fromisoformat(str(row["period_end"])[:10])
        overlap_start, overlap_end = max(period_start, start_date), min(period_end, end_date)
        overlap_days = (overlap_end - overlap_start).days + 1
        period_days = (period_end - period_start).days + 1
        if overlap_days <= 0 or period_days <= 0:
            continue
        amount = Decimal(str(row["budget_amount"] or 0)) * Decimal(overlap_days) / Decimal(period_days)
        totals[row["account"]] = totals.get(row["account"], Decimal("0")) + amount
    return [{"account": account, "budget_amount": amount} for account, amount in totals.items()]


def get_reporting_context():
    """Return safe company reporting metadata without weakening Finance Settings permissions."""
    from velora.exceptions import PermissionDenied
    from velora.meta.registry import registry
    try:
        check_permission(registry.get("Finance Settings"), "read")
    except PermissionDenied:
        return {}
    settings = get_table("Finance Settings")
    with db.transaction() as conn:
        row = conn.execute(select(settings.c.base_currency).limit(1)).first()
    return {"base_currency": row[0]} if row and row[0] else {}
