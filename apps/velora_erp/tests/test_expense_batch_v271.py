from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from velora_erp.finance.engine import get_account_balance
from test_cash_transactions import setup_cash, approve, MAKER

T = date.today()


def _accounts(accounts):
    petty = new_doc("Account", account_code="1010", account_name="Petty Cash", account_group="A", account_type="CASH", allow_manual_posting=1).insert(ignore_permissions=True)
    wht = new_doc("Account", account_code="2300", account_name="WHT Payable", account_group="L", account_type="WITHHOLDING_TAX", allow_manual_posting=1).insert(ignore_permissions=True)
    return petty, wht


def _batch(accounts, petty, wht, rows, **kw):
    with session_as(MAKER):
        return new_doc("Expense Batch", petty_cash_account=petty.name, posting_date=T, currency="NGN", exchange_rate=1,
                       wht_payable_account=wht.name, lines=rows, **kw).insert()


def _row(accounts, amount, payee="Vendor", ref="R-1", **kw):
    return {"expense_date": T, "expense_account": accounts["5000"].name, "payee": payee, "description": "Supplies", "amount": amount, "reference": ref, **kw}


def test_expense_batch_posts_gross_net_and_wht_in_one_posting(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        petty, wht = _accounts(accounts)
        b = approve(_batch(accounts, petty, wht, [_row(accounts, 1000, wht_rate=5), _row(accounts, 400, "Courier", "R-2")]))
        assert (b.total_expenses, b.total_wht, b.net_cash) == (Decimal("1400"), Decimal("50"), Decimal("1350"))
        assert get_account_balance(accounts["5000"].name) == Decimal("1400.000000")
        assert get_account_balance(petty.name) == Decimal("-1350.000000")
        assert get_account_balance(wht.name) == Decimal("-50.000000")
        assert b.posting_batch
    finally:
        velora.shutdown()


def test_preflight_reports_every_bad_row_and_blocks_duplicates(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        petty, wht = _accounts(accounts)
        with pytest.raises(ValidationError) as e:
            _batch(accounts, petty, wht, [_row(accounts, 0), _row(accounts, 10, payee=" "), _row(accounts, 10, wht_rate=120)])
        msg = str(e.value)
        assert "Row 1" in msg and "Row 2" in msg and "Row 3" in msg
        with pytest.raises(ValidationError, match="Duplicate of row 1"):
            _batch(accounts, petty, wht, [_row(accounts, 50), _row(accounts, 50)])
        approve(_batch(accounts, petty, wht, [_row(accounts, 50)]))
        with pytest.raises(ValidationError, match="Already paid in"):
            _batch(accounts, petty, wht, [_row(accounts, 50)])
        _batch(accounts, petty, wht, [_row(accounts, 50, allow_duplicate=1)])     # deliberate second payment
    finally:
        velora.shutdown()


def test_bank_batch_detects_duplicate_statement_lines(tmp_path):
    accounts, c, s = setup_cash(tmp_path)
    try:
        def make(**kw):
            with session_as(MAKER):
                return new_doc("Batch Bank Transaction", bank_account=accounts["1000"].name, posting_date=T, currency="NGN", exchange_rate=1,
                               transactions=[{"transaction_date": T, "direction": "Receipt", "description": "Deposit", "offset_account": accounts["4000"].name,
                                              "amount": 700, "reference": "TRX-9", **kw}]).insert()
        approve(make())
        with pytest.raises(ValidationError, match="Already posted in"):
            make()
        make(allow_duplicate=1)
    finally:
        velora.shutdown()
