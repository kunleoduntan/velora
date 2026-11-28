from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import new_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_cash_transactions import setup_cash, MAKER
from test_invoice_settlement_v271 import _sales_invoice, _purchase_invoice
from velora_erp.finance import controls_check as cc

T = date.today()
RANGE = (T - timedelta(days=400), T + timedelta(days=1))


def _by(res):
    return {f["code"]: f for f in res["findings"]}


def test_duplicate_invoices_and_bills_are_flagged_once_per_pair(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        a = _sales_invoice(accounts, customer, 1000)
        b = _sales_invoice(accounts, customer, 1000)
        _sales_invoice(accounts, customer, 999)
        _purchase_invoice(accounts, supplier, 300)
        _purchase_invoice(accounts, supplier, 300)
        f = _by(cc.run_checks(*RANGE))
        assert f["AR-DUP"]["count"] == 1 and {f["AR-DUP"]["rows"][0]["first"], f["AR-DUP"]["rows"][0]["second"]} == {a.name, b.name}
        assert f["AP-DUP"]["count"] == 1 and f["AP-DUP"]["amount"] == 300
    finally:
        velora.shutdown()


def _dated_invoice(accounts, customer, amount, invoice_date, due_date):
    from test_cash_transactions import approve
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=invoice_date, posting_date=invoice_date, due_date=due_date, party=customer.name, currency="NGN", exchange_rate=1,
                      narration="Dated", lines=[{"description": "Service", "quantity": 1, "rate": amount, "amount": amount, "account": accounts["4000"].name}]).insert()
    return approve(inv)


def test_stale_balances_use_due_date_and_ignore_paid_invoices(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        jan1 = date(T.year, 1, 1)
        old = _dated_invoice(accounts, customer, 500, jan1, jan1 + timedelta(days=1))
        recent = _dated_invoice(accounts, customer, 70, jan1, jan1 + timedelta(days=100))
        today = jan1 + timedelta(days=121)                                    # old: 120 days late, recent: 20 days late
        span = (jan1, jan1 + timedelta(days=200))
        f = _by(cc.run_checks(*span, stale_days=90, today=today))
        assert [r["document"] for r in f["AR-STALE"]["rows"]] == [old.name] and f["AR-STALE"]["rows"][0]["days_overdue"] == 120
        assert _by(cc.run_checks(*span, stale_days=5, today=today))["AR-STALE"]["count"] == 2
        assert _by(cc.run_checks(*span, stale_days=5, today=jan1))["AR-STALE"]["count"] == 0       # nothing is late before the due dates
        assert recent.name not in [r["document"] for r in f["AR-STALE"]["rows"]]
    finally:
        velora.shutdown()


def test_credit_limit_and_bills_against_orders(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        _sales_invoice(accounts, customer, 1000)
        customer.credit_limit = 800                 # the limit was lowered after the sale (submitting is already blocked above the limit)
        customer.save(ignore_permissions=True)
        f = _by(cc.run_checks(*RANGE))
        assert f["AR-CREDIT"]["count"] == 1 and f["AR-CREDIT"]["rows"][0]["over_by"] == 200
        _purchase_invoice(accounts, supplier, 50)
        g = _by(cc.run_checks(*RANGE, scope="Payables"))
        assert g["AP-NO-PO"]["count"] == 1 and "AR-DUP" not in g and "AP-OVER-PO" in g
    finally:
        velora.shutdown()


def test_control_accounts_agree_when_everything_goes_through_parties(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        _sales_invoice(accounts, customer, 1000)
        _purchase_invoice(accounts, supplier, 300)
        f = _by(cc.run_checks(*RANGE))
        for code in ("CX-CUSTOMER-UNTAGGED", "CX-CUSTOMER-TIEOUT", "CX-SUPPLIER-UNTAGGED", "CX-SUPPLIER-TIEOUT"):
            assert f[code]["count"] == 0, code
    finally:
        velora.shutdown()


def test_validation_and_summary(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with pytest.raises(ValidationError):
            cc.run_checks(T, T - timedelta(days=1))
        with pytest.raises(ValidationError):
            cc.run_checks(*RANGE, scope="Everything")
        res = cc.run_checks(*RANGE)
        assert res["summary"]["checks"] == len(res["findings"]) == 11 and res["summary"]["errors"] == 0
    finally:
        velora.shutdown()
