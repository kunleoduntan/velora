from datetime import date
from decimal import Decimal

from sqlalchemy import case, func, select

from velora import db, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.reporting_utils import financial_year_start


def _split(value):
    value = Decimal(value or 0)
    return (value, Decimal(0)) if value >= 0 else (Decimal(0), -value)


def execute(filters):
    check_access()
    end = filters.get("to_date") or date.today()
    start = filters.get("from_date") or financial_year_start(end)
    if start > end:
        throw("From Date cannot be after To Date.")
    include_zero = bool(filters.get("include_zero_balances"))
    ledger = get_table("Account Ledger Record")
    accounts = get_table("Account")
    groups = get_table("Account Group")
    conditions = [ledger.c.posting_date <= end]
    if filters.get("cost_centre"):
        conditions.append(ledger.c.cost_centre == filters["cost_centre"])
    opening_debit = func.coalesce(func.sum(case((ledger.c.posting_date < start, ledger.c.base_debit), else_=0)), 0).label("opening_debit")
    opening_credit = func.coalesce(func.sum(case((ledger.c.posting_date < start, ledger.c.base_credit), else_=0)), 0).label("opening_credit")
    period_debit = func.coalesce(func.sum(case((ledger.c.posting_date >= start, ledger.c.base_debit), else_=0)), 0).label("period_debit")
    period_credit = func.coalesce(func.sum(case((ledger.c.posting_date >= start, ledger.c.base_credit), else_=0)), 0).label("period_credit")
    query = select(ledger.c.account, opening_debit, opening_credit, period_debit, period_credit).where(*conditions).group_by(ledger.c.account)
    with db.transaction() as conn:
        balances = {r["account"]: dict(r) for r in conn.execute(query).mappings()}
        account_rows = [dict(r) for r in conn.execute(
            select(accounts.c.name, accounts.c.account_code, accounts.c.account_name, accounts.c.account_group, accounts.c.disabled)
        ).mappings()]
        group_rows = [dict(r) for r in conn.execute(
            select(groups.c.name, groups.c.group_code, groups.c.group_name, groups.c.parent_group, groups.c.root_type, groups.c.is_group, groups.c.disabled)
        ).mappings()]
        settings = get_table("Finance Settings")
        setting = conn.execute(select(settings.c.base_currency).limit(1)).first()
    currency = setting[0] if setting else ""

    accounts_by_group = {}
    for account in account_rows:
        accounts_by_group.setdefault(account["account_group"], []).append(account)
    children = {}
    for group in group_rows:
        children.setdefault(group["parent_group"], []).append(group)
    group_by_name = {g["name"]: g for g in group_rows}
    active_cache = {}

    def group_active(name):
        if name in active_cache:
            return active_cache[name]
        found = any((include_zero or (a["name"] in balances and any(Decimal(str(balances[a["name"]][k] or 0)) != 0 for k in ("opening_debit", "opening_credit", "period_debit", "period_credit")))) for a in accounts_by_group.get(name, []) if not a["disabled"])
        found = found or any(group_active(child["name"]) for child in children.get(name, []) if not child["disabled"])
        active_cache[name] = found
        return found

    columns = [
        Column("account", "Account"),
        Column("opening_debit", "Opening Debit", "Currency"),
        Column("opening_credit", "Opening Credit", "Currency"),
        Column("period_debit", "Period Debit", "Currency"),
        Column("period_credit", "Period Credit", "Currency"),
        Column("closing_debit", "Closing Debit", "Currency"),
        Column("closing_credit", "Closing Credit", "Currency"),
    ]
    rb = ReportBuilder("Trial Balance", columns, subtitle=f"{start:%d %b %Y} to {end:%d %b %Y}", currency=currency)

    def walk_group(group, depth):
        name = group["name"]
        if group["disabled"] or not group_active(name):
            return
        rb.section(f"{group['group_code']} · {group['group_name']}", indent=depth)
        for child in sorted(children.get(name, []), key=lambda x: x["group_code"]):
            walk_group(child, depth + 1)
        for account in sorted(accounts_by_group.get(name, []), key=lambda x: x["account_code"]):
            if account["disabled"]:
                continue
            b = balances.get(account["name"], {})
            od_net = Decimal(str(b.get("opening_debit", 0) or 0)) - Decimal(str(b.get("opening_credit", 0) or 0))
            pd = Decimal(str(b.get("period_debit", 0) or 0))
            pc = Decimal(str(b.get("period_credit", 0) or 0))
            if not include_zero and od_net == 0 and pd == 0 and pc == 0:
                continue
            od, oc = _split(od_net)
            cd, cc = _split(od_net + pd - pc)
            rb.row({
                "account": f"{account['account_code']} · {account['account_name']}",
                "opening_debit": od or None,
                "opening_credit": oc or None,
                "period_debit": pd or None,
                "period_credit": pc or None,
                "closing_debit": cd or None,
                "closing_credit": cc or None,
            }, indent=depth + 1)
        rb.subtotal(f"Total {group['group_name']}")

    for root in ("Asset", "Liability", "Equity", "Income", "Expense"):
        root_groups = [g for g in children.get(None, []) if g["root_type"] == root]
        if not any(group_active(g["name"]) for g in root_groups if not g["disabled"]):
            continue
        rb.section(root)
        for group in sorted(root_groups, key=lambda x: x["group_code"]):
            walk_group(group, 1)
        rb.subtotal(f"Total {root}")
    rb.total("TOTAL")
    return rb
