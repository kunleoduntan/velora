"""Realised exchange differences (IAS 21.28): a foreign invoice settled at another rate clears at its booked rate and the difference is posted."""
from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as

from test_cash_transactions import MAKER, approve, setup_cash
from velora_erp.finance.engine import get_account_balance

D = Decimal


def _world(tmp_path, configure=True):
    accounts, customer, supplier = setup_cash(tmp_path)
    def acct(code, name, typ, root):
        grp = get_list("Account Group", filters={"root_type": root}, fields=["name"], limit=1)[0]["name"]
        return new_doc("Account", account_code=code, account_name=name, account_group=grp, account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True)
    gain, loss = acct("4800", "Realised FX gain", "REVENUE", "Income"), acct("5800", "Realised FX loss", "OPERATING_EXPENSE", "Expense")
    if configure:
        fs = get_doc("Finance Settings", get_list("Finance Settings", fields=["name"], limit=1)[0]["name"])
        fs.realised_exchange_gain_account, fs.realised_exchange_loss_account = gain.name, loss.name
        fs.save(ignore_permissions=True)
    return accounts, customer, supplier, gain, loss


def _sales_invoice(a, c, amount=1000, rate=1500):
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=c.name, currency="USD", exchange_rate=rate, narration="x",
                      lines=[{"account": a["4000"].name, "description": "s", "amount": amount}]).insert()
    return approve(inv)


def _receipt(a, c, inv, amount, rate):
    with session_as(MAKER):
        r = new_doc("Receipt", receipt_date=date.today(), posting_date=date.today(), purpose="Customer Receipt", currency="USD", exchange_rate=rate, cash_account=a["1000"].name, narration="r",
                    lines=[{"account": a["1100"].name, "amount": amount, "party_type": "Customer", "party": c.name, "invoice_reference": inv.name, "allocation_amount": amount}]).insert()
    return approve(r)


def test_receipt_at_a_better_rate_posts_a_realised_gain_and_clears_the_receivable(tmp_path):
    a, c, s, gain, loss = _world(tmp_path)
    try:
        inv = _sales_invoice(a, c)
        r = _receipt(a, c, inv, 1000, 1600)
        assert get_account_balance(a["1100"].name) == 0 and get_account_balance(a["1000"].name) == D(1_600_000)
        assert get_account_balance(gain.name) == -D(100_000) and get_account_balance(loss.name) == 0
        from velora_erp.finance.party_accounting import get_party_balances
        assert D(str(get_party_balances("Customer", c.name, as_of=date.today())[0]["balance"])) == 0
        rows = get_list("Account Ledger Record", filters={"source_name": r.name}, fields=["account", "debit", "credit", "base_debit", "base_credit", "fx_role"], limit=10, ignore_permissions=True)
        assert sorted(x["fx_role"] or "" for x in rows) == ["", "Carried at original rate", "Exchange difference"]
        assert sum(D(x["base_debit"]) for x in rows) == sum(D(x["base_credit"]) for x in rows)
        with session_as("Administrator") if False else session_as(MAKER.__class__("fin@example.test", frozenset({"Finance Manager"}))):
            get_doc("Receipt", r.name).cancel(ignore_permissions=True)
        assert get_account_balance(a["1100"].name) == D(1_500_000) and get_account_balance(gain.name) == 0 and get_account_balance(a["1000"].name) == 0
    finally:
        velora.shutdown()


def test_part_payments_at_different_rates_add_up_exactly_and_a_worse_rate_is_a_loss(tmp_path):
    a, c, s, gain, loss = _world(tmp_path)
    try:
        inv = _sales_invoice(a, c, amount=999, rate=1501.37)
        _receipt(a, c, inv, 333, 1480)
        _receipt(a, c, inv, 333, 1520)
        _receipt(a, c, inv, 333, 1500)
        assert get_account_balance(a["1100"].name) == 0, "the receivable closes to exactly zero however the cents round"
        cash = D(333) * 1480 + D(333) * 1520 + D(333) * 1500
        assert get_account_balance(a["1000"].name) == cash
        assert get_account_balance(gain.name) + get_account_balance(loss.name) == D(inv.base_grand_total) - cash
        # supplier side: a payment at a worse rate than the bill was booked at is a loss
        with session_as(MAKER):
            pi = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=s.name, currency="USD", exchange_rate=1500, narration="b",
                         lines=[{"account": a["5000"].name, "description": "g", "amount": 200}]).insert()
        pi = approve(pi)
        loss_before = get_account_balance(loss.name)
        with session_as(MAKER):
            p = new_doc("Payment", payment_date=date.today(), posting_date=date.today(), purpose="Supplier Payment", currency="USD", exchange_rate=1550, cash_account=a["1000"].name, narration="p",
                        lines=[{"account": a["2100"].name, "amount": 200, "party_type": "Supplier", "party": s.name, "invoice_reference": pi.name, "allocation_amount": 200}]).insert()
        approve(p)
        assert get_account_balance(a["2100"].name) == 0 and get_account_balance(loss.name) - loss_before == D(200) * 50
    finally:
        velora.shutdown()


def test_without_the_exchange_accounts_the_settlement_is_refused_with_a_clear_message(tmp_path):
    a, c, s, gain, loss = _world(tmp_path, configure=False)
    try:
        inv = _sales_invoice(a, c)
        with pytest.raises(Exception, match="realised exchange gain"):
            _receipt(a, c, inv, 1000, 1600)
        r = _receipt(a, c, inv, 1000, 1500)                                 # no difference, so no account is needed
        assert get_account_balance(a["1100"].name) == 0
    finally:
        velora.shutdown()
