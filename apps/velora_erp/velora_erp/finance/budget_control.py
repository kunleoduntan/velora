"""Enterprise budget control: effective budgets, availability checks in the posting engine, annual spread.

Configuration (company setting ``finance.budget_control``)::

    {"mode": "Off" | "Warn" | "Block",           # default Off - nothing changes until a company opts in
     "budget_name": "FY2027 Operating Budget",    # optional; else the one active budget covering the posting date
     "control_period": "Month" | "YTD" | "Year",  # how much budget a posting may draw on (default Month)
     "tolerance_percent": 0,                      # overspend allowed before the control triggers
     "unbudgeted": "Allow" | "Warn" | "Block"}    # expense with no budget line at all (default Allow)

Only the *increase* of Expense spend is controlled; income, balance-sheet and reversing postings never are.
A Block is overridden only explicitly: ``with override(reason):`` by a user holding the configurable approval action
``budget.override`` (see approval_authority). Approving or submitting a document never overrides it by itself.
The effective budget is the approved Financial Budget plus its approved Budget Adjustments, so approved
transfers and increases are available immediately and the original budget is never edited.
"""
from __future__ import annotations

import calendar
from datetime import date
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func

from velora import db, throw
from velora.db.tables import get_table

ZERO = Decimal("0")
SETTING_KEY = "finance.budget_control"
MODES = ("Off", "Warn", "Block")
PERIODS = ("Month", "YTD", "Year")
UNBUDGETED = ("Allow", "Warn", "Block")
CONTROLLED_EVENTS = {"Original", "Adjustment"}


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def get_config() -> dict:
    try:
        from velora.settings import get_setting
        raw = get_setting(SETTING_KEY, {}) or {}
    except Exception:  # noqa: BLE001 - no settings table yet
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    return {"mode": raw.get("mode") if raw.get("mode") in MODES else "Off",
            "budget_name": raw.get("budget_name") or None,
            "control_period": raw.get("control_period") if raw.get("control_period") in PERIODS else "Month",
            "tolerance_percent": _d(raw.get("tolerance_percent")),
            "unbudgeted": raw.get("unbudgeted") if raw.get("unbudgeted") in UNBUDGETED else "Allow"}


def set_config(*, mode="Off", budget_name=None, control_period="Month", tolerance_percent=0, unbudgeted="Allow") -> dict:
    if mode not in MODES or control_period not in PERIODS or unbudgeted not in UNBUDGETED:
        throw("Invalid budget control option.")
    tolerance = _d(tolerance_percent)
    if tolerance < 0 or tolerance > 100:
        throw("Tolerance must be between 0 and 100 percent.")
    from velora.settings import set_setting
    value = {"mode": mode, "budget_name": budget_name or None, "control_period": control_period,
             "tolerance_percent": str(tolerance), "unbudgeted": unbudgeted}
    set_setting(SETTING_KEY, value)
    return get_config()


def spread_annual_budget(year_start: date, annual_amount, *, weights=None) -> list[dict]:
    """Split an annual amount into 12 calendar-month rows that add up exactly (remainder goes to the last month).

    ``weights`` is an optional list of 12 non-negative numbers (seasonality); default is an even spread.
    """
    total = _d(annual_amount)
    if total < 0:
        throw("Annual budget cannot be negative.")
    if year_start.day != 1:
        throw("The budget year must start on the first day of a month.")
    w = [Decimal("1")] * 12 if weights is None else [_d(x) for x in weights]
    if len(w) != 12 or any(x < 0 for x in w) or sum(w) <= 0:
        throw("Weights must be 12 non-negative numbers with a positive total.")
    rows, used = [], ZERO
    for i in range(12):
        y, m = year_start.year + (year_start.month - 1 + i) // 12, (year_start.month - 1 + i) % 12 + 1
        amount = (total - used) if i == 11 else (total * w[i] / sum(w)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        used += amount
        rows.append({"period_start": date(y, m, 1), "period_end": date(y, m, calendar.monthrange(y, m)[1]), "budget_amount": amount})
    return rows


# ---- effective budget ----------------------------------------------------------------------------------

def _active_budgets_for(posting_date: date, budget_name=None):
    parent, fy = get_table("Financial Budget"), get_table("Financial Year")
    q = (select(parent.c.name, parent.c.budget_name, parent.c.financial_year, fy.c.start_date, fy.c.end_date)
         .select_from(parent.join(fy, parent.c.financial_year == fy.c.name))
         .where(parent.c.docstatus == 1, parent.c.approval_status == "Approved", parent.c.budget_status == "Active",
                func.coalesce(parent.c.is_group_budget, 0) == 0,
                fy.c.start_date <= posting_date, fy.c.end_date >= posting_date))
    if budget_name:
        q = q.where(parent.c.budget_name == budget_name)
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(q.order_by(parent.c.name)).mappings()]


def effective_lines(budget_doc_name: str) -> list[dict]:
    """Approved budget lines plus approved adjustment lines (signed), as one list."""
    out = []
    bl, ad, adl = get_table("Financial Budget Line"), get_table("Budget Adjustment"), get_table("Budget Adjustment Line")
    cols = ("account", "period_start", "period_end", "cost_centre", "branch", "business_unit", "project", "department")
    with db.transaction() as conn:
        for r in conn.execute(select(*(bl.c[c] for c in cols), bl.c.budget_amount).where(bl.c.parent == budget_doc_name)).mappings():
            out.append({**{c: r[c] for c in cols}, "amount": _d(r["budget_amount"]), "source": "Budget"})
        q = (select(*(adl.c[c] for c in cols), adl.c.change_amount, ad.c.name.label("adjustment"))
             .select_from(adl.join(ad, adl.c.parent == ad.c.name))
             .where(ad.c.financial_budget == budget_doc_name, ad.c.docstatus == 1, ad.c.approval_status == "Approved"))
        for r in conn.execute(q).mappings():
            out.append({**{c: r[c] for c in cols}, "amount": _d(r["change_amount"]), "source": r["adjustment"]})
    return out


def _period_range(period: str, on: date, year_start: date, year_end: date):
    if period == "Month":
        return date(on.year, on.month, 1), date(on.year, on.month, calendar.monthrange(on.year, on.month)[1])
    if period == "YTD":
        return year_start, date(on.year, on.month, calendar.monthrange(on.year, on.month)[1])
    return year_start, year_end


def _actual(account: str, start: date, end: date, cost_centre=None) -> Decimal:
    t = get_table("Account Ledger Record")
    q = select(func.coalesce(func.sum(t.c.base_debit), 0) - func.coalesce(func.sum(t.c.base_credit), 0)).where(
        t.c.account == account, t.c.posting_date >= start, t.c.posting_date <= end)
    if cost_centre:
        q = q.where(t.c.cost_centre == cost_centre)
    with db.transaction() as conn:
        return _d(conn.execute(q).scalar())


def availability(account: str, on: date, *, cost_centre=None, budget_doc=None, period="Month") -> dict | None:
    """Budget, actual and available for one account at a date, or None when the account has no budget line."""
    cfg = get_config()
    budgets = [budget_doc] if budget_doc else _active_budgets_for(on, cfg["budget_name"])
    if len(budgets) != 1:
        return None
    b = budgets[0]
    start, end = _period_range(period, on, _date(b["start_date"]), _date(b["end_date"]))
    lines = [l for l in effective_lines(b["name"]) if l["account"] == account]
    if not lines:
        return None
    scoped = [l for l in lines if cost_centre and l["cost_centre"] == cost_centre]
    uncentred = [l for l in lines if not l["cost_centre"]]
    if cost_centre and scoped:
        chosen, cc = scoped, cost_centre
    elif uncentred or not cost_centre:
        chosen, cc = (uncentred or lines), None
    else:
        return None
    budget = sum((l["amount"] for l in chosen if start <= _date(l["period_start"]) and _date(l["period_end"]) <= end), ZERO)
    actual = _actual(account, start, end, cc)
    return {"budget_doc": b["name"], "budget_name": b["budget_name"], "account": account, "cost_centre": cc, "period": period,
            "from": start, "to": end, "budget": budget, "actual": actual, "available": budget - actual}


# ---- posting-engine hook ----------------------------------------------------------------------------------

def check_posting(*, lines, posting_date, exchange_rate, posting_event, source_doctype=None) -> list[str]:
    """Called by the posting engine before a new batch is created. Returns Warn-mode messages; raises in Block mode."""
    cfg = get_config()
    if cfg["mode"] == "Off" or posting_event not in CONTROLLED_EVENTS or source_doctype in ("Opening Balance Entry",):
        return []
    posting_date = _date(posting_date)
    rate = _d(exchange_rate) or Decimal("1")
    spend: dict[tuple, Decimal] = {}
    for ln in lines:
        get = (lambda k: ln.get(k)) if isinstance(ln, dict) else (lambda k: getattr(ln, k, None))
        net = (_d(get("debit")) - _d(get("credit"))) * rate
        if net:
            key = (get("account"), get("cost_centre") or None)
            spend[key] = spend.get(key, ZERO) + net
    spend = {k: v for k, v in spend.items() if v > 0}
    if not spend:
        return []
    acc = get_table("Account")
    with db.transaction() as conn:
        roots = {r["name"]: r["root_type"] for r in conn.execute(select(acc.c.name, acc.c.root_type).where(acc.c.name.in_([k[0] for k in spend]))).mappings()}
    spend = {k: v for k, v in spend.items() if roots.get(k[0]) == "Expense"}
    if not spend:
        return []
    budgets = _active_budgets_for(posting_date, cfg["budget_name"])
    if len(budgets) > 1:
        msg = "More than one active budget covers this date. Select the controlling budget in Budget Control settings."
        if cfg["mode"] == "Block":
            throw(msg)
        return [msg]
    if not budgets:
        return []
    # Serialise concurrent postings against the same budget so two can't both spend the last unit of currency.
    parent = get_table("Financial Budget")
    with db.transaction() as conn:
        conn.execute(select(parent.c.name).where(parent.c.name == budgets[0]["name"]).with_for_update()).first()
    issues = []
    for (account, cc), amount in sorted(spend.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        info = availability(account, posting_date, cost_centre=cc, budget_doc=budgets[0], period=cfg["control_period"])
        if info is None:
            if cfg["unbudgeted"] != "Allow":
                issues.append((cfg["unbudgeted"], f"Account {account} has no budget in {budgets[0]['budget_name']}; spend of {amount:,.2f} is unbudgeted."))
            continue
        limit = info["budget"] * (Decimal("1") + cfg["tolerance_percent"] / Decimal("100"))
        if info["actual"] + amount > limit:
            over = info["actual"] + amount - info["budget"]
            where = f" / {cc}" if info["cost_centre"] else ""
            issues.append((cfg["mode"], f"Budget exceeded for {account}{where} ({info['period']} {info['from']}..{info['to']}): "
                           f"budget {info['budget']:,.2f}, already spent {info['actual']:,.2f}, this posting {amount:,.2f}, over by {over:,.2f}."))
    if not issues:
        return []
    messages = [m for _, m in issues]
    blocking = [m for level, m in issues if level == "Block"]
    if blocking:
        reason = _OVERRIDE.get()
        if reason:
            from velora.permissions import get_session
            from velora_erp.finance.approval_authority import describe, is_authorised
            session = get_session()
            if (session.attributes or {}).get("service_account") or not is_authorised("budget.override", user=session.user, roles=session.roles):
                throw(f"Only {describe('budget.override')} may override a budget block.")
            _record(messages + [f"Override reason: {reason}"], source_doctype, overridden=True)
            return messages
        throw(" ".join(blocking) + " Get a budget adjustment approved, or have an authorised budget approver post it with an explicit override.")
    _record(messages, source_doctype, overridden=False)
    return messages


_OVERRIDE: ContextVar = ContextVar("velora_budget_override", default=None)


@contextmanager
def override(reason: str):
    """Explicitly post past a budget Block. Needs a reason and the ``budget.override`` authority; always audited.

    Holding the authority is NOT enough on its own: approving or submitting a document never overrides a budget.
    """
    if not reason or not str(reason).strip():
        throw("A reason is required to override a budget block.")
    token = _OVERRIDE.set(str(reason).strip())
    try:
        yield
    finally:
        _OVERRIDE.reset(token)


def _record(messages, source_doctype, *, overridden):
    try:
        from velora.activity import record_event
        record_event("integration", "Budget override" if overridden else "Budget warning", doctype=source_doctype or "Financial Posting Batch",
                     summary=" | ".join(messages)[:900], metadata={"overridden": overridden})
    except Exception:  # noqa: BLE001 - auditing must never break posting
        pass


# ---- budget vs actual with adjustments --------------------------------------------------------------------

def budget_utilisation(budget_name: str, *, as_of: date, group_by_cost_centre=False) -> list[dict]:
    """Per account (and optionally cost centre): original, adjustments, revised, actual to date, available, utilisation %."""
    budgets = [b for b in _active_budgets_for(as_of, budget_name)]
    if len(budgets) != 1:
        throw(f"Budget {budget_name!r} is not an active approved budget for {as_of}.")
    b = budgets[0]
    start = _date(b["start_date"])
    rows: dict[tuple, dict] = {}
    for l in effective_lines(b["name"]):
        if _date(l["period_start"]) > as_of:
            continue
        key = (l["account"], (l["cost_centre"] or "") if group_by_cost_centre else "")
        r = rows.setdefault(key, {"account": key[0], "cost_centre": key[1] or None, "original": ZERO, "adjustments": ZERO})
        r["original" if l["source"] == "Budget" else "adjustments"] += l["amount"]
    out = []
    for (account, cc), r in sorted(rows.items()):
        actual = _actual(account, start, as_of, cc or None)
        revised = r["original"] + r["adjustments"]
        out.append({**r, "revised": revised, "actual": actual, "available": revised - actual,
                    "utilisation_percent": (actual / revised * 100).quantize(Decimal("0.01")) if revised else None})
    return out
