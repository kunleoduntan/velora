"""Conversion rounding: a balanced foreign-currency entry whose lines round separately posts the cent difference to the exchange rounding account."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pytest
import velora
from sqlalchemy import func, select
from velora import db, get_doc, get_list, new_doc
from velora.db.tables import get_table
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_cash_transactions import MAKER, approve, setup_cash
from velora_erp.finance.engine import get_account_balance

D = Decimal
FM = MAKER.__class__("fin@example.test", frozenset({"Finance Manager"}))


def _invoice(a, c, rate, amounts, currency="USD"):
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=c.name, currency=currency, exchange_rate=rate, narration="r",
                      lines=[{"account": a["4000"].name, "description": "x", "amount": v} for v in amounts]).insert()
    return approve(inv)


def _rounding_account():
    grp = get_list("Account Group", filters={"root_type": "Expense"}, fields=["name"], limit=1)[0]["name"]
    acct = new_doc("Account", account_code="5890", account_name="Exchange rounding", account_group=grp, account_type="OPERATING_EXPENSE").insert(ignore_permissions=True)
    fs = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1)[0]["name"])
    fs.exchange_rounding_account = acct.name
    fs.save(ignore_permissions=True)
    return acct


def test_unconfigured_rounding_is_refused_with_a_clear_message(tmp_path):
    a, c, s = setup_cash(tmp_path)
    try:
        with pytest.raises(ValidationError, match="Exchange Rounding Account"):
            _invoice(a, c, 1500.5, [10.01, 10.01, 10.01])
    finally:
        velora.shutdown()


@pytest.mark.parametrize("rate,amounts", [(1500.5, [10.01, 10.01, 10.01]), (1.5, [0.01, 0.01, 0.01]), (1532.77, [3.33, 3.33, 3.34, 7.77])])
def test_rounding_difference_posts_to_the_rounding_account_and_cancels_cleanly(tmp_path, rate, amounts):
    a, c, s = setup_cash(tmp_path)
    try:
        r = _rounding_account()
        inv = _invoice(a, c, rate, amounts)
        receivable = get_account_balance(a["1100"].name)
        assert receivable == (sum(D(str(x)) for x in amounts) * D(str(rate))).quantize(D("0.01"), ROUND_HALF_UP), "the receivable is the invoice total at the rate"
        assert abs(get_account_balance(r.name)) <= D("0.01") * len(amounts)
        led = get_table("Account Ledger Record")
        with db.transaction() as conn:
            dr, cr = conn.execute(select(func.sum(led.c.base_debit), func.sum(led.c.base_credit))).one()
        assert D(str(dr)) == D(str(cr))
        with session_as(FM):
            get_doc("Sales Invoice", inv.name).cancel(ignore_permissions=True)
        assert get_account_balance(r.name) == 0 and get_account_balance(a["1100"].name) == 0
    finally:
        velora.shutdown()


def test_a_real_imbalance_is_still_refused(tmp_path):
    a, c, s = setup_cash(tmp_path)
    try:
        _rounding_account()
        from velora_erp.finance.engine import post_financial_transaction
        with pytest.raises(ValidationError, match="larger than conversion rounding"):
            post_financial_transaction(source_doctype="Test", source_name="T1", posting_date=date.today(), currency="USD", exchange_rate=1500,
                                       lines=[{"account": a["1000"].name, "debit": 10, "credit": 0, "base_debit": 15000},
                                              {"account": a["4000"].name, "debit": 0, "credit": 10, "base_credit": 14000, "fx_role": "Carried at original rate"}])
    finally:
        velora.shutdown()
