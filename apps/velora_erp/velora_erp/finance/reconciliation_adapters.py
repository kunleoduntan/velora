"""Live source adapters for Finance control-account reconciliation.

These adapters read operational subledgers and the Account Ledger. They never
create journals or mutate balances; differences are returned as reviewable exceptions.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy import func, select
from velora import db, get_doc, get_list
from velora.db.tables import get_table
from velora_erp.finance.engine import get_account_balance
from .control_reconciliation import reconcile_control


def _as_date(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def _require_current_operational_snapshot(as_of_date, source_name):
    """Prevent comparing a current-state subledger to a historical GL balance."""
    requested = _as_date(as_of_date)
    if requested and requested != date.today():
        raise ValueError(
            f"{source_name} currently exposes current-state balances only; "
            "a historical as-of reconciliation requires dated balance snapshots."
        )
    return date.today()


def reconcile_employee_finance(*, as_of_date=None, tolerance="0.01"):
    """Reconcile current employee loan and advance receivables by control account."""
    asof=_require_current_operational_snapshot(as_of_date, "Employee finance")
    sources=defaultdict(list)
    loans=get_list("Employee Loan",filters=[["docstatus","=",1]],fields=["name","employee","loan_account","outstanding_principal","status"],limit=100000,ignore_permissions=True)
    for loan in loans:
        if loan.get("status") in ("Settled","Written Off"): continue
        amount=Decimal(str(loan.get("outstanding_principal") or 0))
        if amount:
            if not loan.get("loan_account"):
                raise ValueError(f"Employee Loan {loan['name']} has an outstanding balance but no loan receivable account.")
            sources[("Employee Loans",loan["loan_account"])].append({"source_type":"Employee Loan","source_name":loan["name"],"balance":amount})
    advances=get_list("Employee Advance",filters=[["docstatus","=",1]],fields=["name","employee","advance_account","outstanding_amount","status"],limit=100000,ignore_permissions=True)
    for advance in advances:
        if advance.get("status")=="Settled": continue
        amount=Decimal(str(advance.get("outstanding_amount") or 0))
        if amount:
            if not advance.get("advance_account"):
                raise ValueError(f"Employee Advance {advance['name']} has an outstanding balance but no advance receivable account.")
            sources[("Employee Advances",advance["advance_account"])].append({"source_type":"Employee Advance","source_name":advance["name"],"balance":amount})
    results=[]
    for (kind,account),rows in sorted(sources.items()):
        results.append(reconcile_control(control_type=kind,control_account=account,gl_balance=get_account_balance(account,as_of=asof),source_balances=rows,tolerance=tolerance,as_of_date=str(asof or "Current")))
    return results


def reconcile_inventory(*, as_of_date=None, tolerance="0.01"):
    """Reconcile inventory valuation by configured stock asset account."""
    asof = _as_date(as_of_date)
    settings_rows=get_list("Inventory Settings",fields=["name","default_inventory_asset_account"],limit=1,ignore_permissions=True)
    if not settings_rows: return []
    default_account=settings_rows[0].get("default_inventory_asset_account")
    items=get_list("Inventory Item",filters=[["is_stock_item","=",1],["disabled","=",0]],fields=["name","stock_asset_account"],limit=100000,ignore_permissions=True)
    item_account={x["name"]:(x.get("stock_asset_account") or default_account) for x in items}
    if not item_account: return []
    ledger=get_table("Stock Ledger Record")
    query=select(ledger.c.item_code,func.coalesce(func.sum(ledger.c.stock_value_difference),0).label("value")).group_by(ledger.c.item_code)
    if asof: query=query.where(ledger.c.posting_date<=asof)
    with db.transaction() as conn: rows=conn.execute(query).mappings().all()
    source=defaultdict(list)
    for row in rows:
        item_code = row["item_code"]
        value=Decimal(str(row["value"] or 0))
        account=item_account.get(item_code)
        if value and not account:
            raise ValueError(f"Inventory Item {item_code} has a stock balance but no stock asset account mapping.")
        if account and value:
            source[account].append({"source_type":"Inventory Item","source_name":item_code,"balance":value})
    return [reconcile_control(control_type="Inventory",control_account=account,gl_balance=get_account_balance(account,as_of=asof),source_balances=detail,tolerance=tolerance,as_of_date=str(asof or "Current")) for account,detail in sorted(source.items())]


def reconcile_fixed_assets(*, as_of_date=None, tolerance="0.01"):
    """Reconcile current financial-book cost, depreciation and impairment.

    Only books explicitly configured to post to the GL are included. Tax and
    management books are excluded. Book balances are current-state records, so
    historical dates are rejected rather than compared with today's balances.
    """
    asof = _require_current_operational_snapshot(as_of_date, "Fixed assets")
    books=get_list("Fixed Asset Depreciation Book",filters=[["posts_to_gl","=",1],["is_default","=",1],["disabled","=",0]],fields=["name","book_code"],limit=10000,ignore_permissions=True)
    book_names={x["name"] for x in books}
    if not book_names:return []
    balances=get_list("Fixed Asset Book Balance",fields=["name","asset","depreciation_book","acquisition_cost","accumulated_depreciation","accumulated_impairment","accumulated_depreciation_account"],limit=100000,ignore_permissions=True)
    source=defaultdict(list)
    for balance in balances:
        if balance.get("depreciation_book") not in book_names: continue
        asset=get_doc("Fixed Asset",balance["asset"],ignore_permissions=True)
        cost=Decimal(str(balance.get("acquisition_cost") or 0))
        depreciation=Decimal(str(balance.get("accumulated_depreciation") or 0))
        impairment=Decimal(str(balance.get("accumulated_impairment") or 0))
        if cost:
            if not asset.asset_account:
                raise ValueError(f"Fixed Asset {asset.name} has acquisition cost but no asset account.")
            source[("Fixed Assets",asset.asset_account)].append({"source_type":"Fixed Asset Book Cost","source_name":balance["name"],"balance":cost})
        depreciation_account = balance.get("accumulated_depreciation_account") or asset.accumulated_depreciation_account
        if depreciation:
            if not depreciation_account:
                raise ValueError(f"Fixed Asset {asset.name} has accumulated depreciation but no accumulated depreciation account.")
            source[("Fixed Assets",depreciation_account)].append({"source_type":"Fixed Asset Accumulated Depreciation","source_name":balance["name"],"balance":-depreciation})
        impairment_account = getattr(asset, "impairment_account", None)
        if impairment:
            if not impairment_account:
                raise ValueError(f"Fixed Asset {asset.name} has accumulated impairment but no impairment account.")
            source[("Fixed Assets",impairment_account)].append({"source_type":"Fixed Asset Accumulated Impairment","source_name":balance["name"],"balance":-impairment})
    return [reconcile_control(control_type="Fixed Assets",control_account=account,gl_balance=get_account_balance(account, as_of=asof),source_balances=detail,tolerance=tolerance,as_of_date=asof.isoformat()) for (_,account),detail in sorted(source.items())]
