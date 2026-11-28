"""Governed year-end closing calculations; never posts a journal itself.

Account balances use the ledger convention debit minus credit. The returned
proposal is a reviewable journal draft and must be approved and posted through
the Financial Posting Engine by the application's normal workflow.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
import hashlib
import json


class YearEndCloseError(ValueError):
    pass


def _money(value, label):
    try:
        amount = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise YearEndCloseError(f"{label} must be a valid decimal amount") from None
    if not amount.is_finite():
        raise YearEndCloseError(f"{label} must be finite")
    return amount


def build_year_end_closing_proposal(*, balances, retained_earnings_account, posting_date,
                                    financial_year, currency, precision=2):
    """Build a balanced, non-posting close proposal for income/expense accounts.

    `balances` rows require account, account_type (Income or Expense), and
    balance (debit minus credit). Balance-sheet accounts are rejected. Empty
    and duplicate accounts are rejected; zero balances are omitted.
    """
    if not str(retained_earnings_account or "").strip():
        raise YearEndCloseError("A retained earnings account is required")
    if not str(posting_date or "").strip() or not str(financial_year or "").strip():
        raise YearEndCloseError("Posting date and financial year are required")
    try:
        date.fromisoformat(str(posting_date))
    except ValueError:
        raise YearEndCloseError("Posting date must be a valid ISO date (YYYY-MM-DD)") from None
    if not str(currency or "").strip():
        raise YearEndCloseError("Currency is required")
    if isinstance(precision, bool) or not isinstance(precision, int) or not 0 <= precision <= 8:
        raise YearEndCloseError("Currency precision must be an integer between 0 and 8")
    if not isinstance(balances, (list, tuple)) or not balances:
        raise YearEndCloseError("At least one income or expense account balance is required")
    quantum = Decimal(1).scaleb(-precision)
    seen = set()
    lines = []
    total_debit = Decimal(0)
    total_credit = Decimal(0)
    for index, row in enumerate(balances, 1):
        if not isinstance(row, dict):
            raise YearEndCloseError(f"Balance row {index} must be an object")
        account = str(row.get("account") or "").strip()
        account_type = str(row.get("account_type") or "").strip()
        if not account:
            raise YearEndCloseError(f"Balance row {index} has no account")
        if account == retained_earnings_account:
            raise YearEndCloseError("Retained earnings cannot also be an income or expense source account")
        if account in seen:
            raise YearEndCloseError(f"Duplicate account balance: {account}")
        seen.add(account)
        if account_type not in {"Income", "Expense"}:
            raise YearEndCloseError(f"Account {account} is not an Income or Expense account")
        balance = _money(row.get("balance"), f"Balance for {account}").quantize(quantum, rounding=ROUND_HALF_UP)
        if balance == 0:
            continue
        # Closing entries reverse each P&L account balance (debit minus credit).
        # Revenue is normally credit-normal (negative); expenses debit-normal (positive).
        debit = max(-balance, Decimal(0))
        credit = max(balance, Decimal(0))
        lines.append({"account": account, "account_type": account_type,
                      "debit": debit, "credit": credit,
                      "description": f"Close {account_type.lower()} balance"})
        total_debit += debit
        total_credit += credit
    if not lines:
        raise YearEndCloseError("There are no non-zero income or expense balances to close")
    net = total_debit - total_credit
    if net > 0:
        lines.append({"account": retained_earnings_account, "account_type": "Equity",
                      "debit": Decimal(0), "credit": net,
                      "description": "Transfer net profit to retained earnings"})
        total_credit += net
    elif net < 0:
        lines.append({"account": retained_earnings_account, "account_type": "Equity",
                      "debit": -net, "credit": Decimal(0),
                      "description": "Transfer net loss from retained earnings"})
        total_debit += -net
    lines.sort(key=lambda line: (line["account"], line["description"]))
    for line in lines:
        line["debit"] = line["debit"].quantize(quantum, rounding=ROUND_HALF_UP)
        line["credit"] = line["credit"].quantize(quantum, rounding=ROUND_HALF_UP)
    total_debit = total_debit.quantize(quantum, rounding=ROUND_HALF_UP)
    total_credit = total_credit.quantize(quantum, rounding=ROUND_HALF_UP)
    if total_debit != total_credit:
        raise YearEndCloseError("Generated closing proposal is not balanced")
    canonical = {
        "posting_date": str(posting_date), "financial_year": str(financial_year),
        "currency": str(currency), "retained_earnings_account": retained_earnings_account,
        "lines": [{**line, "debit": str(line["debit"]), "credit": str(line["credit"])} for line in lines],
    }
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "status": "Draft Proposal", "requires_independent_approval": True,
        "posting_engine_required": True, "posted": False,
        "posting_date": str(posting_date), "financial_year": str(financial_year),
        "currency": str(currency), "retained_earnings_account": retained_earnings_account,
        "lines": lines, "total_debit": total_debit, "total_credit": total_credit,
        "net_profit": net.quantize(quantum, rounding=ROUND_HALF_UP), "fingerprint": fingerprint,
    }
