"""Enterprise budget planning: monthly account plan, last-year projection, allocation, scenarios and variance.

The approved budget stays a list of one-calendar-month ``Financial Budget Line`` rows, because budget control,
adjustments and reporting all read those. This module is the planning layer *above* them:

* ``Financial Budget Account`` rows hold one account across Jan-Dec. ``plan_to_lines`` turns them into lines.
* ``allocate_lines`` shares unassigned lines across branches or cost centres so the totals tie to the cent.
* ``project_months`` proposes a plan from last year's actuals (equal spread or the same monthly pattern).
* ``scenario_rows`` prices what-if cases. Scenarios are analysis only and never change the approved budget.
* ``variance`` compares plan with actual per account and month.

Everything here is pure arithmetic over plain dicts except the two ``*_actuals`` readers, so it is easy to test.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func

from velora import db, throw
from velora.db.tables import get_table

ZERO = Decimal("0")
CENT = Decimal("0.01")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DIMENSIONS = ("cost_centre", "branch", "business_unit", "project", "department")
BASIS_FIELD = "basis_value"


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:  # noqa: BLE001
        throw(f"{v!r} is not a valid number.")


def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def _q(v: Decimal) -> Decimal:
    return v.quantize(CENT, ROUND_HALF_UP)


def _get(row, key, default=None):
    return row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)


# ---- calendar -------------------------------------------------------------------------------------------

def year_months(year_start, year_end) -> dict[str, tuple[date, date]]:
    """Map 'jan'..'dec' to the calendar month of the financial year that carries that name (the year may start in any month)."""
    start, end = _date(year_start), _date(year_end)
    if start.day != 1:
        throw("The financial year must start on the first day of a month.")
    out, y, m = {}, start.year, start.month
    while (y, m) <= (end.year, end.month):
        first, last = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        out[MONTHS[m - 1]] = (first, min(last, end))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if len(out) > 12:
            throw("A financial year longer than twelve months cannot be planned month by month.")
    return out


# ---- plan rows -> lines -------------------------------------------------------------------------------------

def row_total(row) -> Decimal:
    return sum((_d(_get(row, m)) for m in MONTHS), ZERO)


def plan_to_lines(rows, year_start, year_end, *, header=None) -> list[dict]:
    """One budget line per non-zero month of every plan row. Header dimensions fill what a row leaves blank."""
    months = year_months(year_start, year_end)
    header = header or {}
    lines = []
    for index, row in enumerate(rows or [], 1):
        account = _get(row, "account")
        if not account:
            throw(f"Monthly plan row {index}: select an account.")
        for key in MONTHS:
            amount = _d(_get(row, key))
            if amount < 0:
                throw(f"Monthly plan row {index}: {key.title()} cannot be negative.")
            if not amount:
                continue
            if key not in months:
                throw(f"Monthly plan row {index}: {key.title()} is outside this financial year, so it must be zero.")
            first, last = months[key]
            line = {"account": account, "period_start": first, "period_end": last, "budget_amount": _q(amount),
                    "line_notes": _get(row, "row_notes") or None}
            for dim in DIMENSIONS:
                line[dim] = _get(row, dim) or header.get(dim) or None
            lines.append(line)
    return lines


# ---- allocation ---------------------------------------------------------------------------------------------

def allocation_percentages(allocations, method, *, dimension) -> list[Decimal]:
    """Percentages per allocation row. Rows ticked 'Keep this %' (or all rows for Custom %) keep what was typed;
    the remaining share goes to the others equally or by basis value. The result always totals exactly 100."""
    rows = list(allocations or [])
    if not rows:
        throw("Add at least one branch or cost centre to share the budget across.")
    seen = set()
    for i, r in enumerate(rows, 1):
        key = _get(r, dimension)
        if not key:
            throw(f"Allocation row {i}: select a {dimension.replace('_', ' ')}.")
        if key in seen:
            throw(f"Allocation row {i}: {key} appears twice.")
        seen.add(key)
    n = len(rows)
    if method == "Custom %":
        pct = [_d(_get(r, "allocation_percent")) for r in rows]
    else:
        keep = [bool(_get(r, "is_locked")) for r in rows]
        fixed = [(_d(_get(r, "allocation_percent")) if k else ZERO) for r, k in zip(rows, keep)]
        left = Decimal("100") - sum(fixed, ZERO)
        free = [i for i in range(n) if not keep[i]]
        if left < 0:
            throw("The percentages you kept add up to more than 100.")
        if not free:
            pct = fixed
        else:
            if method == "Proportional to Basis":
                weights = [_d(_get(rows[i], BASIS_FIELD)) for i in free]
                if any(w < 0 for w in weights) or sum(weights, ZERO) <= 0:
                    throw("Enter a positive basis value for every row that is not kept at a fixed percentage.")
            else:
                weights = [Decimal("1")] * len(free)
            total_w = sum(weights, ZERO)
            pct = list(fixed)
            for i, w in zip(free, weights):
                pct[i] = _q(left * w / total_w)
            drift = Decimal("100") - sum(pct, ZERO)
            pct[free[-1]] += drift
    if any(p < 0 for p in pct):
        throw("Allocation percentages cannot be negative.")
    if _q(sum(pct, ZERO)) != Decimal("100.00"):
        throw(f"Allocation percentages add up to {sum(pct, ZERO):,.2f}, not 100.")
    return pct


def split_amount(amount: Decimal, pct: list[Decimal]) -> list[Decimal]:
    """Share an amount by percentages; the largest share absorbs the rounding so parts add up to the amount."""
    parts = [_q(amount * p / Decimal("100")) for p in pct]
    parts[max(range(len(pct)), key=lambda i: pct[i])] += amount - sum(parts, ZERO)
    return parts


def allocate_lines(lines, allocations, method, *, dimension) -> list[dict]:
    """Share lines that have no ``dimension`` of their own across the allocation rows. Specific lines stay as they are."""
    pct = allocation_percentages(allocations, method, dimension=dimension)
    targets = [_get(a, dimension) for a in allocations]
    out = []
    for line in lines:
        if line.get(dimension):
            out.append(line)
            continue
        for target, part in zip(targets, split_amount(_d(line["budget_amount"]), pct)):
            if part:
                out.append({**line, dimension: target, "budget_amount": part})
    return out


def allocation_table(allocations, method, total, *, dimension) -> list[dict]:
    """Allocation rows with their percentage and amount filled in (for the form and the workbench)."""
    pct = allocation_percentages(allocations, method, dimension=dimension)
    amounts = split_amount(_d(total), pct)
    return [{**(dict(a) if isinstance(a, dict) else a.as_dict()), "allocation_percent": float(p), "allocated_amount": float(x)}
            for a, p, x in zip(allocations, pct, amounts)]


# ---- projection ---------------------------------------------------------------------------------------------

PROJECTION_METHODS = ("Equal Distribution", "Historical Pattern")


def project_months(previous: dict, method: str, growth_percent=0) -> dict[str, Decimal]:
    """Propose twelve months from last year's monthly actuals (``previous`` maps 'jan'..'dec' to an amount)."""
    if method not in PROJECTION_METHODS:
        throw("Projection method must be Equal Distribution or Historical Pattern.")
    growth = Decimal("1") + _d(growth_percent) / Decimal("100")
    if growth < 0:
        throw("A decrease of more than 100% is not possible.")
    base = {m: max(_d(previous.get(m)), ZERO) for m in MONTHS}
    total = _q(sum(base.values(), ZERO) * growth)
    if method == "Equal Distribution":
        share = _q(total / 12)
        out = {m: share for m in MONTHS}
        out["dec"] += total - sum(out.values(), ZERO)
        return out
    out = {m: _q(base[m] * growth) for m in MONTHS}
    last = next((m for m in reversed(MONTHS) if out[m]), "dec")
    out[last] += total - sum(out.values(), ZERO)
    return out


# ---- scenarios ----------------------------------------------------------------------------------------------

def scenario_rows(base_total, scenarios) -> list[dict]:
    """Each scenario priced against the base plan, plus the probability-weighted expected total of the active ones."""
    base = _d(base_total)
    out, weight, weighted = [], ZERO, ZERO
    for s in scenarios or []:
        pct = _d(_get(s, "adjustment_percent"))
        if pct <= Decimal("-100"):
            throw("A scenario cannot reduce the budget by 100% or more.")
        total = _q(base * (Decimal("1") + pct / Decimal("100")))
        row = {"scenario_name": _get(s, "scenario_name"), "scenario_type": _get(s, "scenario_type"),
               "adjustment_percent": float(pct), "probability": float(_d(_get(s, "probability"))),
               "is_active": bool(_get(s, "is_active", 1)), "total_budget": float(total),
               "variance_from_base": float(total - base),
               "variance_percent": float(_q((total - base) / base * 100)) if base else None}
        out.append(row)
        if row["is_active"] and row["probability"] > 0:
            weight += _d(row["probability"])
            weighted += total * _d(row["probability"])
    expected = _q(weighted / weight) if weight else None
    return [{**r, "expected_total": float(expected) if expected is not None else None} for r in out]


def scenario_months(base_months: dict, pct) -> dict[str, float]:
    factor = Decimal("1") + _d(pct) / Decimal("100")
    return {m: float(_q(_d(base_months.get(m)) * factor)) for m in MONTHS}


# ---- actuals ------------------------------------------------------------------------------------------------

def _actual_expression(t, root_type):
    debit, credit = func.coalesce(func.sum(t.c.base_debit), 0), func.coalesce(func.sum(t.c.base_credit), 0)
    return debit - credit if root_type in ("Asset", "Expense") else credit - debit


def _root_types(accounts) -> dict[str, str]:
    accounts = sorted({a for a in accounts if a})
    if not accounts:
        return {}
    acc = get_table("Account")
    with db.transaction() as conn:
        return {r["name"]: r["root_type"] for r in conn.execute(select(acc.c.name, acc.c.root_type).where(acc.c.name.in_(accounts))).mappings()}


def monthly_actuals(accounts, start, end, *, cost_centre=None, branch=None) -> dict[str, dict[str, Decimal]]:
    """Actual per account per month name ('jan'..'dec'), signed so income and expense are both positive."""
    start, end = _date(start), _date(end)
    roots = _root_types(accounts)
    if not roots:
        return {}
    t = get_table("Account Ledger Record")
    q = (select(t.c.account, func.extract("month", t.c.posting_date).label("m"),
                func.coalesce(func.sum(t.c.base_debit), 0).label("dr"), func.coalesce(func.sum(t.c.base_credit), 0).label("cr"))
         .where(t.c.account.in_(list(roots)), t.c.posting_date >= start, t.c.posting_date <= end)
         .group_by(t.c.account, "m"))
    if cost_centre:
        q = q.where(t.c.cost_centre == cost_centre)
    if branch:
        q = q.where(t.c.branch == branch)
    out: dict[str, dict[str, Decimal]] = {}
    with db.transaction() as conn:
        for r in conn.execute(q).mappings():
            dr, cr = _d(r["dr"]), _d(r["cr"])
            value = dr - cr if roots.get(r["account"]) in ("Asset", "Expense") else cr - dr
            out.setdefault(r["account"], {})[MONTHS[int(r["m"]) - 1]] = value
    return out


def previous_year_range(year_start, year_end) -> tuple[date, date]:
    start, end = _date(year_start), _date(year_end)
    prev_end = start - timedelta(days=1)
    try:
        prev_start = start.replace(year=start.year - 1)
    except ValueError:  # 29 Feb
        prev_start = start.replace(year=start.year - 1, day=28)
    return prev_start, min(prev_end, end)


def previous_year_actuals(rows, year_start, year_end) -> dict[tuple, Decimal]:
    """Last year's actual total for each (account, cost centre, branch) used by the plan rows."""
    accounts = {_get(r, "account") for r in rows or [] if _get(r, "account")}
    roots = _root_types(accounts)
    if not roots:
        return {}
    start, end = previous_year_range(year_start, year_end)
    t = get_table("Account Ledger Record")
    q = (select(t.c.account, t.c.cost_centre, t.c.branch,
                func.coalesce(func.sum(t.c.base_debit), 0).label("dr"), func.coalesce(func.sum(t.c.base_credit), 0).label("cr"))
         .where(t.c.account.in_(list(roots)), t.c.posting_date >= start, t.c.posting_date <= end)
         .group_by(t.c.account, t.c.cost_centre, t.c.branch))
    by_key: dict[tuple, Decimal] = {}
    with db.transaction() as conn:
        for r in conn.execute(q).mappings():
            dr, cr = _d(r["dr"]), _d(r["cr"])
            value = dr - cr if roots.get(r["account"]) in ("Asset", "Expense") else cr - dr
            cc, br = r["cost_centre"] or None, r["branch"] or None
            # a plan row is matched at exactly the specificity it names, so each posting counts once per level
            for key in {(r["account"], cc, br), (r["account"], None, None), (r["account"], cc, None), (r["account"], None, br)}:
                by_key[key] = by_key.get(key, ZERO) + value
    return {k: _q(v) for k, v in by_key.items()}


def last_year_for(row, table: dict) -> Decimal:
    return table.get((_get(row, "account"), _get(row, "cost_centre") or None, _get(row, "branch") or None), ZERO)


# ---- variance -----------------------------------------------------------------------------------------------

def variance(plan_rows, actuals: dict, *, through_month: int) -> list[dict]:
    """Budget, actual and variance to date for each plan row. Variance = budget - actual (positive = under budget for
    expenses, behind target for income); the sign meaning is returned per row so the screen does not guess."""
    roots = _root_types([_get(r, "account") for r in plan_rows])
    out = []
    for row in plan_rows:
        account = _get(row, "account")
        budget_ytd = sum((_d(_get(row, m)) for m in MONTHS[:through_month]), ZERO)
        actual_ytd = sum((actuals.get(account, {}).get(m, ZERO) for m in MONTHS[:through_month]), ZERO)
        root = roots.get(account)
        out.append({"account": account, "cost_centre": _get(row, "cost_centre"), "branch": _get(row, "branch"), "root_type": root,
                    "annual_budget": float(row_total(row)), "budget_to_date": float(budget_ytd), "actual_to_date": float(actual_ytd),
                    "variance": float(budget_ytd - actual_ytd),
                    "variance_percent": float(_q((budget_ytd - actual_ytd) / budget_ytd * 100)) if budget_ytd else None,
                    "utilisation_percent": float(_q(actual_ytd / budget_ytd * 100)) if budget_ytd else None,
                    "better_when": "lower" if root in ("Expense", "Asset") else "higher",
                    "projected_year_end": float(_q(actual_ytd / through_month * 12)) if through_month else None})
    return out


# ---- workbench service --------------------------------------------------------------------------------------

def _year(name):
    from velora import get_doc
    year = get_doc("Financial Year", name, ignore_permissions=True)
    if not year:
        throw("Select a valid Financial Year.")
    return year


def default_through_month(year_start, year_end, today=None) -> int:
    """How many months of the plan have run (1-12), judged from today's date and clipped to the year."""
    today = today or date.today()
    start, end = _date(year_start), _date(year_end)
    if today < start:
        return 0
    if today > end:
        return 12
    return min(12, (today.year - start.year) * 12 + today.month - start.month + 1)


def propose_plan(financial_year, *, method="Historical Pattern", growth_percent=0, root_types=("Expense",), limit=300) -> list[dict]:
    """Draft plan rows for every account that had activity last year (Expense by default), projected into this year."""
    year = _year(financial_year)
    start, end = previous_year_range(year.start_date, year.end_date)
    acc, t = get_table("Account"), get_table("Account Ledger Record")
    with db.transaction() as conn:
        accounts = [r["name"] for r in conn.execute(select(acc.c.name).where(acc.c.root_type.in_(list(root_types)))
                                                       .order_by(acc.c.name)).mappings()]
    if not accounts:
        return []
    by_account = monthly_actuals(accounts, start, end)
    # last year's months are matched to this year's month names by calendar month, whatever the year start
    rows = []
    for account in accounts:
        previous = by_account.get(account)
        if not previous or not any(previous.values()):
            continue
        months = project_months(previous, method, growth_percent)
        rows.append({"account": account, **{m: float(v) for m, v in months.items()}, "total": float(sum(months.values(), ZERO)),
                     "previous_year_actual": float(sum(previous.values(), ZERO))})
        if len(rows) >= limit:
            break
    return rows


def project_rows(financial_year, rows, *, method="Historical Pattern", growth_percent=0) -> list[dict]:
    """Projection for chosen plan rows (account, cost_centre, branch) - the 'Project from last year' tool."""
    year = _year(financial_year)
    start, end = previous_year_range(year.start_date, year.end_date)
    out = []
    for row in rows or []:
        actual = monthly_actuals([row.get("account")], start, end, cost_centre=row.get("cost_centre"), branch=row.get("branch")).get(row.get("account"), {})
        months = project_months(actual, method, growth_percent)
        out.append({"account": row.get("account"), "cost_centre": row.get("cost_centre"), "branch": row.get("branch"),
                    **{m: float(v) for m, v in months.items()}, "previous_year_actual": float(sum(actual.values(), ZERO))})
    return out


def workbench(budget_name, through_month=None) -> dict:
    """Everything the Budget Workbench screen shows for one budget."""
    from velora import get_doc, get_list
    doc = get_doc("Financial Budget", budget_name)
    year = _year(doc.financial_year)
    if through_month in (None, ""):
        through = default_through_month(year.start_date, year.end_date)
    else:
        through = min(max(int(through_month), 0), 12)
    rows = list(doc.account_budgets or [])
    months = year_months(year.start_date, year.end_date)
    plan = [{"account": r.account, "cost_centre": r.cost_centre, "branch": r.branch, **{m: float(_d(getattr(r, m))) for m in MONTHS},
             "total": float(row_total(r)), "previous_year_actual": float(_d(r.previous_year_actual)), "row_notes": r.row_notes} for r in rows]
    month_totals = {m: float(sum((_d(r[m]) for r in plan), ZERO)) for m in MONTHS}
    actual_by_account = monthly_actuals([r["account"] for r in plan], year.start_date, year.end_date)
    actual_months = {m: float(sum((v.get(m, ZERO) for v in actual_by_account.values()), ZERO)) for m in MONTHS}
    total = float(sum(month_totals.values()))
    children = []
    if doc.is_group_budget:
        for c in get_list("Financial Budget", filters=[["parent_budget", "=", doc.name], ["docstatus", "!=", 2]], fields=["name", "budget_name", "total_budget_amount", "approval_status", "budget_status"], limit=500, ignore_permissions=True):
            children.append(c)
    dimension = {"Branch": "branch", "Cost Centre": "cost_centre"}.get(doc.allocate_by or "None")
    allocation = []
    if dimension and doc.allocations:
        allocation = allocation_table(doc.allocations, doc.allocation_method or "Equal", _d(doc.total_budget_amount), dimension=dimension)
    scenarios = scenario_rows(_d(doc.total_budget_amount or total), doc.scenarios or [])
    return {"budget": {"name": doc.name, "budget_name": doc.budget_name, "financial_year": doc.financial_year, "budget_type": doc.budget_type,
                       "budget_against": doc.budget_against, "is_group_budget": bool(doc.is_group_budget), "parent_budget": doc.parent_budget,
                       "approval_status": doc.approval_status, "budget_status": doc.budget_status, "docstatus": doc.docstatus,
                       "currency": doc.currency, "allocate_by": doc.allocate_by, "allocation_method": doc.allocation_method},
            "year": {"start": str(year.start_date), "end": str(year.end_date), "months": {k: [str(a), str(b)] for k, (a, b) in months.items()}},
            "through_month": through, "plan": plan, "month_totals": month_totals, "actual_months": actual_months, "total": total,
            "variance": variance(rows, actual_by_account, through_month=through) if through else [],
            "allocation": allocation, "allocation_dimension": dimension, "scenarios": scenarios,
            "scenario_months": [{"scenario_name": s["scenario_name"], "months": scenario_months(month_totals, s["adjustment_percent"])} for s in scenarios if s["is_active"]],
            "children": children, "children_total": float(sum((_d(c.get("total_budget_amount")) for c in children), ZERO))}
