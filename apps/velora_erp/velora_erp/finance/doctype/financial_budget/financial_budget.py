from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from sqlalchemy import select
from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required


def _budget_fingerprint(doc):
    lines = []
    for line in doc.lines or []:
        lines.append({
            "account": line.account,
            "period_start": str(line.period_start),
            "period_end": str(line.period_end),
            "budget_amount": str(Decimal(str(line.budget_amount or 0))),
            "cost_centre": line.cost_centre or None,
            "branch": line.branch or None,
            "business_unit": line.business_unit or None,
            "project": line.project or None,
            "department": line.department or None,
            "dimensions": line.dimensions or {},
        })
    payload = {"budget_name": doc.budget_name, "budget_scenario": doc.budget_scenario,
               "financial_year": doc.financial_year, "currency": doc.currency,
               "budget_notes": doc.budget_notes or "", "lines": lines}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _prepare_plan(doc, year):
    """Turn the monthly plan, allocation and scenarios into the periodised lines that budget control reads."""
    from velora_erp.finance import budget_planner as bp
    header = {}
    if doc.budget_against == "Cost Centre" and doc.cost_centre:
        header["cost_centre"] = doc.cost_centre
    elif doc.budget_against == "Branch" and doc.branch:
        header["branch"] = doc.branch
    elif doc.budget_against == "Project" and doc.project:
        header["project"] = doc.project
    elif doc.budget_against in ("Cost Centre", "Branch", "Project"):
        throw(f"Select the {doc.budget_against} this budget is against.")
    if doc.budget_against != "Cost Centre":
        doc.cost_centre = None
    if doc.budget_against != "Branch":
        doc.branch = None
    if doc.budget_against != "Project":
        doc.project = None

    if doc.is_group_budget:
        doc.parent_budget = None
    elif doc.parent_budget:
        if doc.parent_budget == doc.name:
            throw("A budget cannot be its own parent.")
        parent = get_doc("Financial Budget", doc.parent_budget, ignore_permissions=True)
        if not parent or not parent.is_group_budget:
            throw("The parent budget must be a group (roll-up) budget.")
        if parent.financial_year != doc.financial_year:
            throw("A budget and its parent must be for the same financial year.")

    rows = list(doc.account_budgets or [])
    seen = set()
    for index, row in enumerate(rows, 1):
        key = (row.account, row.cost_centre or "", row.branch or "")
        if key in seen:
            throw(f"Monthly plan row {index}: {row.account} is planned twice for the same cost centre and branch.")
        seen.add(key)
    last_year = bp.previous_year_actuals(rows, year.start_date, year.end_date) if rows else {}
    for row in rows:
        row.total = float(bp.row_total(row))
        row.previous_year_actual = float(bp.last_year_for(row, last_year))

    if rows:
        lines = bp.plan_to_lines(rows, year.start_date, year.end_date, header=header)
        dimension = {"Branch": "branch", "Cost Centre": "cost_centre"}.get(doc.allocate_by or "None")
        if dimension:
            if header.get(dimension):
                throw(f"This budget is already against one {dimension.replace('_', ' ')}, so it cannot also be shared across {doc.allocate_by.lower()}es.")
            lines = bp.allocate_lines(lines, doc.allocations, doc.allocation_method or "Equal", dimension=dimension)
        doc.set("lines", lines)
        doc._link_children()                       # the new rows need their parent, name and order like any others
    elif doc.allocate_by in ("Branch", "Cost Centre") and doc.allocations:
        throw("Add the monthly plan before sharing it across allocations.")

    total = sum((Decimal(str(l.budget_amount or 0)) for l in doc.lines), Decimal("0"))
    doc.total_budget_amount = float(total)

    dimension = {"Branch": "branch", "Cost Centre": "cost_centre"}.get(doc.allocate_by or "None")
    if dimension and doc.allocations:
        shown = bp.allocation_table(doc.allocations, doc.allocation_method or "Equal", total, dimension=dimension)
        for row, info in zip(doc.allocations, shown):
            row.allocation_percent, row.allocated_amount = info["allocation_percent"], info["allocated_amount"]
    for row, info in zip(doc.scenarios or [], bp.scenario_rows(total, doc.scenarios or [])):
        row.total_budget, row.variance_from_base = info["total_budget"], info["variance_from_base"]


class FinancialBudget(Document):
    """Approved financial budgets are planning data only and never create GL postings."""

    def validate(self):
        validate_approval_transition(self)
        self.budget_name = (self.budget_name or "").strip()
        if not self.budget_name or not self.financial_year:
            throw("Budget Name and Financial Year are required.")
        settings = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not settings or not settings[0].get("base_currency"):
            throw("Configure the company base currency before creating a financial budget.")
        self.currency = settings[0]["base_currency"]
        year = get_doc("Financial Year", self.financial_year, ignore_permissions=True)
        if not year:
            throw("Select a valid Financial Year.")
        _prepare_plan(self, year)
        if not self.lines and not self.is_group_budget:
            throw("A financial budget must contain at least one periodised budget line.")

        account_table = get_table("Account")
        groups = get_table("Account Group")
        seen = set()
        for index, line in enumerate(self.lines, 1):
            if not line.account or not line.period_start or not line.period_end:
                throw(f"Budget line {index}: Account, Period Start and Period End are required.")
            try:
                amount = Decimal(str(line.budget_amount if line.budget_amount not in (None, "") else 0))
            except (InvalidOperation, TypeError, ValueError):
                throw(f"Budget line {index}: Budget Amount must be a valid decimal number.")
            if not amount.is_finite() or amount < 0:
                throw(f"Budget line {index}: Budget Amount must be finite and non-negative.")
            start, end = date.fromisoformat(str(line.period_start)[:10]), date.fromisoformat(str(line.period_end)[:10])
            if start > end or start < year.start_date or end > year.end_date:
                throw(f"Budget line {index}: period must fall within Financial Year {self.financial_year}.")
            if start.day != 1:
                throw(f"Budget line {index}: Period Start must be the first day of a calendar month.")
            import calendar
            if end.day != calendar.monthrange(end.year, end.month)[1] or (start.year, start.month) != (end.year, end.month):
                throw(f"Budget line {index}: each budget line must represent exactly one calendar month.")
            with db.transaction() as conn:
                account = conn.execute(
                    select(account_table.c.name, account_table.c.disabled, groups.c.disabled.label("group_disabled"))
                    .select_from(account_table.join(groups, account_table.c.account_group == groups.c.name))
                    .where(account_table.c.name == line.account)
                ).mappings().first()
            if not account or account["disabled"] or account["group_disabled"]:
                throw(f"Budget line {index}: select an active posting account.")
            if line.cost_centre:
                from velora_erp.finance.engine import _validate_cost_centre
                _validate_cost_centre(line.cost_centre, index)
            dimensions = line.dimensions or {}
            if not isinstance(dimensions, dict):
                throw(f"Budget line {index}: Additional Accounting Dimensions must be a JSON object.")
            from velora_erp.finance.engine import _validate_dimensions
            _validate_dimensions(dimensions)
            key = (line.account, start.isoformat(), end.isoformat(), line.cost_centre or "", line.branch or "",
                   line.business_unit or "", line.project or "", line.department or "",
                   json.dumps(dimensions, sort_keys=True, separators=(",", ":")))
            if key in seen:
                throw(f"Budget line {index}: duplicate account, period and dimension allocation.")
            seen.add(key)

        old = getattr(self, "_old", None) or {}
        fingerprint = _budget_fingerprint(self)
        if approval_required(self.doctype) and old.get("approval_status") == "Approved" and self.approval_status == "Approved":
            if old.get("approval_hash") != fingerprint or self.approval_hash != fingerprint:
                throw("An approved financial budget is immutable. Reset approval before changing its amounts or dimensions.")
        else:
            self.flags.trusted_fields = set(getattr(self.flags, "trusted_fields", ()) or ()) | {"approval_hash"}
            self.approval_hash = fingerprint if self.approval_status == "Approved" else None
        self.budget_status = {"Approved": "Approved", "Rejected": "Rejected"}.get(self.approval_status, "Draft")

    def before_submit(self):
        ensure_approved(self, required=True)
        if self.approval_hash != _budget_fingerprint(self):
            throw("The financial budget changed after approval. Reset approval and obtain a new approval decision.")
        existing = get_list("Financial Budget", filters=[["budget_name", "=", self.budget_name], ["docstatus", "=", 1]], fields=["name"], limit=2, ignore_permissions=True)
        if existing and existing[0]["name"] != self.name:
            throw(f"An active submitted budget named {self.budget_name!r} already exists. Use a distinct budget name for a revised version.")

    def on_submit(self):
        db_update(self, budget_status="Active")

def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted financial budget is retained for reporting and audit.")
