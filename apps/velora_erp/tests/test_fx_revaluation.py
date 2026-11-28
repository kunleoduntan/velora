"""Period-end revaluation of foreign-currency monetary items (IAS 21.23): unrealised difference, automatic reversal, cancellation."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_cash_transactions import MAKER, approve
from test_fx_settlement import _world, _sales_invoice
from velora_erp.finance.engine import get_account_balance
from velora_erp.finance.doctype.foreign_currency_revaluation.foreign_currency_revaluation import process_due_reversals

D = Decimal


def _rate(ccy, rate, on):
    new_doc("Currency Exchange Rate", from_currency=ccy, to_currency=_base(), rate=rate, effective_date=on).insert(ignore_permissions=True)


def _base():
    from velora_erp.finance.source_documents import finance_settings
    return finance_settings()["base_currency"]


def _configure(gain_loss):
    fs = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1)[0]["name"])
    fs.unrealised_exchange_gain_account, fs.unrealised_exchange_loss_account = gain_loss[0].name, gain_loss[1].name
    fs.save(ignore_permissions=True)


def _acct(code, name, typ, root):
    grp = get_list("Account Group", filters={"root_type": root}, fields=["name"], limit=1)[0]["name"]
    return new_doc("Account", account_code=code, account_name=name, account_group=grp, account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True)


def _reval(on, **kw):
    with session_as(MAKER):
        r = new_doc("Foreign Currency Revaluation", revaluation_date=on, narration="close", **kw).insert()
    return approve(r)


def test_revaluing_a_usd_receivable_posts_unrealised_gain_then_reverses(tmp_path):
    a, c, s, g, l = _world(tmp_path)
    try:
        ug, ul = _acct("4810", "Unrealised FX gain", "REVENUE", "Income"), _acct("5810", "Unrealised FX loss", "OPERATING_EXPENSE", "Expense")
        _configure((ug, ul))
        _sales_invoice(a, c, amount=1000, rate=1500)
        today = date.today()
        _rate("USD", 1600, today)
        r = _reval(today, auto_reverse=1)
        assert D(r.total_gain) == D(100_000) and D(r.total_loss) == 0
        assert get_account_balance(a["1100"].name) == D(1_600_000)
        assert get_account_balance(ug.name) == -D(100_000)
        # a second revaluation at the same rate has nothing to do
        with pytest.raises(ValidationError):
            with session_as(MAKER):
                new_doc("Foreign Currency Revaluation", revaluation_date=today, narration="again").insert()
        done = process_due_reversals(today + timedelta(days=1))
        assert r.name in done
        assert get_account_balance(a["1100"].name) == D(1_500_000) and get_account_balance(ug.name) == 0
        assert process_due_reversals(today + timedelta(days=2)) == []
    finally:
        velora.shutdown()


def test_missing_closing_rate_is_refused_not_guessed(tmp_path):
    a, c, s, g, l = _world(tmp_path)
    try:
        ug, ul = _acct("4810", "Unrealised FX gain", "REVENUE", "Income"), _acct("5810", "Unrealised FX loss", "OPERATING_EXPENSE", "Expense")
        _configure((ug, ul))
        _sales_invoice(a, c, amount=1000, rate=1500)
        from velora_erp.finance import revaluation as rv
        with pytest.raises(Exception):
            rv.revaluation_rows(date.today(), _base())
    finally:
        velora.shutdown()


def test_cancelling_a_revaluation_removes_its_postings(tmp_path):
    a, c, s, g, l = _world(tmp_path)
    try:
        ug, ul = _acct("4810", "Unrealised FX gain", "REVENUE", "Income"), _acct("5810", "Unrealised FX loss", "OPERATING_EXPENSE", "Expense")
        _configure((ug, ul))
        _sales_invoice(a, c, amount=1000, rate=1500)
        _rate("USD", 1400, date.today())
        r = _reval(date.today())
        assert get_account_balance(ul.name) == D(100_000) and get_account_balance(a["1100"].name) == D(1_400_000)
        with session_as(MAKER.__class__("fin@example.test", frozenset({"Finance Manager"}))):
            get_doc("Foreign Currency Revaluation", r.name).cancel(ignore_permissions=True)
        assert get_account_balance(ul.name) == 0 and get_account_balance(a["1100"].name) == D(1_500_000)
    finally:
        velora.shutdown()


def test_ledger_stays_balanced_and_party_control_reconciles_after_revaluation(tmp_path):
    from sqlalchemy import func, select
    from velora import db
    from velora.db.tables import get_table
    from velora_erp.finance.party_accounting import reconcile_party_control_account
    a, c, s, g, l = _world(tmp_path)
    try:
        ug, ul = _acct("4810", "Unrealised FX gain", "REVENUE", "Income"), _acct("5810", "Unrealised FX loss", "OPERATING_EXPENSE", "Expense")
        _configure((ug, ul))
        _sales_invoice(a, c, amount=1000, rate=1500)
        _rate("USD", 1620, date.today())
        _reval(date.today(), auto_reverse=1)
        led = get_table("Account Ledger Record")
        with db.transaction() as conn:
            dr, cr = conn.execute(select(func.sum(led.c.base_debit), func.sum(led.c.base_credit))).one()
        assert D(str(dr)) == D(str(cr)), "base debits equal base credits after revaluation"
        rep = reconcile_party_control_account(a["1100"].name, "Customer")
        assert D(str(rep.get("difference", 0))) == 0, rep
    finally:
        velora.shutdown()


def test_two_currencies_revalue_in_one_document_and_reverse_together(tmp_path):
    a, c, s, g, l = _world(tmp_path)
    try:
        ug, ul = _acct("4810", "Unrealised FX gain", "REVENUE", "Income"), _acct("5810", "Unrealised FX loss", "OPERATING_EXPENSE", "Expense")
        _configure((ug, ul))
        _sales_invoice(a, c, amount=1000, rate=1500)
        with session_as(MAKER):
            eur = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=c.name, currency="EUR", exchange_rate=1600, narration="x",
                          lines=[{"account": a["4000"].name, "description": "s", "amount": 500}]).insert()
        approve(eur)
        _rate("USD", 1600, date.today())       # +100,000
        _rate("EUR", 1500, date.today())       # -50,000
        r = _reval(date.today(), auto_reverse=1)
        assert D(r.total_gain) == 100_000 and D(r.total_loss) == 50_000
        assert get_account_balance(a["1100"].name) == D(1_600_000) + D(750_000)
        assert get_account_balance(ug.name) == -100_000 and get_account_balance(ul.name) == 50_000
        process_due_reversals(date.today() + timedelta(days=1))
        assert get_account_balance(ug.name) == 0 and get_account_balance(ul.name) == 0
        assert get_account_balance(a["1100"].name) == D(1_500_000) + D(800_000)
    finally:
        velora.shutdown()
