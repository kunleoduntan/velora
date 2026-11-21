"""Party subledger balance and control-account reconciliation utilities."""
from datetime import date
from decimal import Decimal
from sqlalchemy import func, select
from velora import db, throw
from velora.db.tables import get_table
from .validation import row


def get_party_balances(party_type: str, party: str, *, as_of: date | None = None) -> list[dict]:
    """Return base-currency balances by party-tracked account for one party."""
    if party_type not in ("Customer", "Supplier", "Employee"):
        throw("Party Type must be Customer, Supplier or Employee.")
    master = row(party_type, party, "name", "disabled")
    if not master or master["disabled"]:
        throw(f"Select an active {party_type}.")
    ledger = get_table("Account Ledger Record")
    account = get_table("Account")
    query = select(
        ledger.c.account,
        account.c.account_code,
        account.c.account_name,
        (func.coalesce(func.sum(ledger.c.base_debit), 0) - func.coalesce(func.sum(ledger.c.base_credit), 0)).label("balance"),
    ).select_from(ledger.join(account, ledger.c.account == account.c.name)).where(
        ledger.c.party_type == party_type, ledger.c.party == party,
    ).group_by(ledger.c.account, account.c.account_code, account.c.account_name).order_by(account.c.account_code)
    if as_of:
        query = query.where(ledger.c.posting_date <= as_of)
    with db.transaction() as conn:
        return [dict(item) for item in conn.execute(query).mappings().all()]


def reconcile_party_control_account(account_name: str, party_type: str) -> dict:
    """Compare the account's net ledger balance with the sum of its party balances."""
    if party_type not in ("Customer", "Supplier", "Employee"):
        throw("Party Type must be Customer, Supplier or Employee.")
    account_row = row("Account", account_name, "name", "root_type", "requires_party", "disabled")
    expected_roots = {"Customer": ("Asset",), "Supplier": ("Liability",), "Employee": ("Asset", "Liability")}
    allowed_roots = expected_roots[party_type]
    if not account_row or account_row["disabled"] or account_row["root_type"] not in allowed_roots or not account_row["requires_party"]:
        throw(f"Select an active party-tracked {' or '.join(allowed_roots)} account.")
    ledger = get_table("Account Ledger Record")
    with db.transaction() as conn:
        total = conn.execute(select(
            (func.coalesce(func.sum(ledger.c.base_debit), 0) - func.coalesce(func.sum(ledger.c.base_credit), 0))
        ).where(ledger.c.account == account_name)).scalar()
        party_total = conn.execute(select(
            (func.coalesce(func.sum(ledger.c.base_debit), 0) - func.coalesce(func.sum(ledger.c.base_credit), 0))
        ).where(ledger.c.account == account_name, ledger.c.party_type == party_type, ledger.c.party.is_not(None))).scalar()
        missing_party = conn.execute(select(func.count()).select_from(ledger).where(
            ledger.c.account == account_name,
            (ledger.c.party_type.is_(None) | ledger.c.party.is_(None)),
        )).scalar()
    control_balance = Decimal(str(total or 0))
    subledger_balance = Decimal(str(party_total or 0))
    difference = control_balance - subledger_balance
    return {
        "account": account_name,
        "party_type": party_type,
        "control_account_balance": control_balance,
        "party_subledger_balance": subledger_balance,
        "difference": difference,
        "unassigned_ledger_rows": int(missing_party or 0),
        "is_reconciled": difference == 0 and not missing_party,
    }
