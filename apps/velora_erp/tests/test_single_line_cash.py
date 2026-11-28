"""A payment or receipt is one amount on the form: no table to fill in, no Entry Side."""
from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from velora_erp.finance.engine import get_account_balance
from test_cash_transactions import MAKER, approve, setup_cash

COMMON = dict(posting_date=date.today(), currency="NGN", exchange_rate=1)


def test_supplier_payment_needs_only_supplier_amount_and_bank(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            pay = new_doc("Payment", payment_date=date.today(), purpose="Supplier Payment", party_type="Supplier", supplier=supplier.name,
                          amount=500, cash_account=accounts["1000"].name, **COMMON).insert()
        assert len(pay.lines) == 1 and pay.lines[0].account == accounts["2100"].name and pay.lines[0].entry_side == "Debit"   # the supplier's own payables account
        assert pay.lines[0].party == supplier.name and Decimal(str(pay.total_amount)) == Decimal("500")
        pay = approve(pay)
        assert get_account_balance(accounts["1000"].name) == Decimal("-500.000000")
        assert get_account_balance(accounts["2100"].name) == Decimal("500.000000")
    finally:
        velora.shutdown()


def test_expense_payment_uses_the_account_on_the_form_and_follows_an_amount_change(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            pay = new_doc("Payment", payment_date=date.today(), purpose="Expense Payment", beneficiary="Landlord", account=accounts["5000"].name,
                          amount=300, cash_account=accounts["1000"].name, **COMMON).insert()
            assert [(l.account, float(l.amount)) for l in pay.lines] == [(accounts["5000"].name, 300.0)]
            pay.amount = 450
            pay.save()
        assert len(pay.lines) == 1 and float(pay.lines[0].amount) == 450.0 and float(pay.total_amount) == 450.0     # still one line, new amount
    finally:
        velora.shutdown()


def test_customer_receipt_credits_the_customers_receivable(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            rc = new_doc("Receipt", receipt_date=date.today(), purpose="Customer Receipt", party_type="Customer", customer=customer.name,
                         amount=1250, cash_account=accounts["1000"].name, **COMMON).insert()
        assert rc.lines[0].entry_side == "Credit" and rc.lines[0].account == accounts["1100"].name
        approve(rc)
        assert get_account_balance(accounts["1100"].name) == Decimal("-1250.000000")
    finally:
        velora.shutdown()


def test_missing_amount_party_or_account_is_explained(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Amount"):
                new_doc("Payment", payment_date=date.today(), purpose="Expense Payment", beneficiary="X", account=accounts["5000"].name, cash_account=accounts["1000"].name, **COMMON).insert()
            with pytest.raises(ValidationError, match="needs the Supplier"):
                new_doc("Payment", payment_date=date.today(), purpose="Supplier Payment", amount=5, cash_account=accounts["1000"].name, **COMMON).insert()
            with pytest.raises(ValidationError, match="Choose the Account"):
                new_doc("Payment", payment_date=date.today(), purpose="Expense Payment", beneficiary="X", amount=5, cash_account=accounts["1000"].name, **COMMON).insert()
    finally:
        velora.shutdown()


def test_several_lines_still_work_and_the_form_amount_becomes_their_total(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            pay = new_doc("Payment", payment_date=date.today(), purpose="Expense Payment", beneficiary="Many", cash_account=accounts["1000"].name,
                          lines=[{"account": accounts["5000"].name, "amount": 100}, {"account": accounts["5000"].name, "amount": 50}], **COMMON).insert()
        assert len(pay.lines) == 2 and float(pay.amount) == 150.0
    finally:
        velora.shutdown()
