from decimal import Decimal
import pytest

from velora_erp.finance.year_end import build_year_end_closing_proposal, YearEndCloseError


def _proposal(balances):
    return build_year_end_closing_proposal(
        balances=balances, retained_earnings_account="RETAINED-EARNINGS",
        posting_date="2026-12-31", financial_year="FY-2026", currency="NGN",
    )


def test_profit_closing_proposal_is_balanced_and_never_posts():
    result = _proposal([
        {"account": "SALES", "account_type": "Income", "balance": "-1000"},
        {"account": "OTHER-INCOME", "account_type": "Income", "balance": "-100"},
        {"account": "SALARIES", "account_type": "Expense", "balance": "600"},
        {"account": "RENT", "account_type": "Expense", "balance": "200"},
    ])
    assert result["net_profit"] == Decimal("300.00")
    assert result["total_debit"] == result["total_credit"] == Decimal("1100.00")
    assert result["status"] == "Draft Proposal"
    assert result["requires_independent_approval"] is True
    assert result["posting_engine_required"] is True
    assert result["posted"] is False
    retained = next(line for line in result["lines"] if line["account"] == "RETAINED-EARNINGS")
    assert retained["credit"] == Decimal("300.00")


def test_loss_closing_proposal_debits_retained_earnings():
    result = _proposal([
        {"account": "SALES", "account_type": "Income", "balance": "-500"},
        {"account": "EXPENSE", "account_type": "Expense", "balance": "800"},
    ])
    assert result["net_profit"] == Decimal("-300.00")
    retained = next(line for line in result["lines"] if line["account"] == "RETAINED-EARNINGS")
    assert retained["debit"] == Decimal("300.00")
    assert result["total_debit"] == result["total_credit"]


@pytest.mark.parametrize("balances", [
    [{"account": "SALES", "account_type": "Income", "balance": "NaN"}],
    [{"account": "BANK", "account_type": "Asset", "balance": "100"}],
    [{"account": "SALES", "account_type": "Income", "balance": "100"}, {"account": "SALES", "account_type": "Income", "balance": "200"}],
    [{"account": "RETAINED-EARNINGS", "account_type": "Income", "balance": "-100"}],
])
def test_invalid_year_end_balances_are_rejected(balances):
    with pytest.raises(YearEndCloseError):
        _proposal(balances)


def test_closing_proposal_fingerprint_is_deterministic_and_input_order_independent():
    a = _proposal([
        {"account": "SALES", "account_type": "Income", "balance": "-100"},
        {"account": "EXPENSE", "account_type": "Expense", "balance": "50"},
    ])
    b = _proposal([
        {"account": "EXPENSE", "account_type": "Expense", "balance": "50"},
        {"account": "SALES", "account_type": "Income", "balance": "-100"},
    ])
    assert a["fingerprint"] == b["fingerprint"]
