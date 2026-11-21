from collections import defaultdict
from decimal import Decimal
from sqlalchemy import func, select

from velora import db, get_list, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access


def D(value):
    return Decimal(str(value or 0))


def execute(filters=None):
    check_access()
    filters = filters or {}
    assets = get_list(
        "Fixed Asset",
        filters={"asset_category": filters["asset_category"]} if filters.get("asset_category") else {},
        fields=["name", "asset_category", "asset_account", "accumulated_depreciation_account",
                "impairment_account", "acquisition_cost", "revaluation_adjustment",
                "accumulated_depreciation", "impairment_loss", "status"],
        limit=100000, ignore_permissions=True,
    )
    if len(assets) >= 100000:
        throw("The asset register exceeds the reconciliation row limit. Filter by Asset Category.")
    register = defaultdict(Decimal)
    asset_names = []
    for asset in assets:
        asset_names.append(asset["name"])
        if asset["status"] not in ("Disposed", "Written Off"):
            register[(asset["asset_account"], "Gross Cost")]+=D(asset["acquisition_cost"])+D(asset["revaluation_adjustment"])
            register[(asset["accumulated_depreciation_account"], "Accumulated Depreciation")]+=D(asset["accumulated_depreciation"])
            if asset.get("impairment_account"):
                register[(asset["impairment_account"], "Accumulated Impairment")]+=D(asset["impairment_loss"])
    ledger_totals = defaultdict(Decimal)
    control_accounts = sorted({account for account, _kind in register})
    if asset_names and control_accounts:
        ledger = get_table("Account Ledger Record")
        query = select(
            ledger.c.account,
            func.coalesce(func.sum(ledger.c.base_debit), 0).label("debit"),
            func.coalesce(func.sum(ledger.c.base_credit), 0).label("credit"),
        ).where(ledger.c.asset.in_(asset_names), ledger.c.account.in_(control_accounts)).group_by(ledger.c.account)
        with db.transaction() as conn:
            rows = conn.execute(query).mappings().all()
        for row in rows:
            # The report stores register balances as positive values for all three classes.
            ledger_totals[row["account"]] = D(row["debit"])-D(row["credit"])
    account_rows = get_list("Account", fields=["name", "account_code", "account_name"], limit=100000, ignore_permissions=True)
    labels = {r["name"]: f'{r.get("account_code") or ""} {r.get("account_name") or r["name"]}'.strip() for r in account_rows}
    rb = ReportBuilder("Fixed Asset General Ledger Reconciliation", [
        Column("account", "Control Account"), Column("balance_type", "Balance Type"),
        Column("register_balance", "Asset Register Balance", "Currency"),
        Column("ledger_balance", "Ledger Balance", "Currency"),
        Column("variance", "Variance", "Currency"),
        Column("status", "Reconciliation Status"),
    ], subtitle="Current asset register balances compared with immutable asset-linked ledger entries.")
    keys = sorted(set(register))
    for account, balance_type in keys:
        register_balance = register.get((account, balance_type), Decimal("0"))
        if balance_type == "Gross Cost":
            ledger_balance = ledger_totals.get(account, Decimal("0"))
        elif balance_type in ("Accumulated Depreciation", "Accumulated Impairment"):
            ledger_balance = -ledger_totals.get(account, Decimal("0"))
        else:
            ledger_balance = ledger_totals.get(account, Decimal("0"))
        variance = register_balance-ledger_balance
        rb.row({"account": labels.get(account, account), "balance_type": balance_type,
                "register_balance": register_balance, "ledger_balance": ledger_balance,
                "variance": variance, "status": "Reconciled" if variance == 0 else "Investigate"})
    return rb
