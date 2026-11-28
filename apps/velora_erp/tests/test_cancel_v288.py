"""ERPNext-style cancel for the accounting documents: cancel removes the posting, unlinks what hangs on it, can be amended."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

import velora
from velora import db, get_doc, new_doc
from velora.db.tables import get_table
from velora.document import amend
from velora.exceptions import DocStatusError, PermissionDenied, ValidationError
from velora.permissions import session_as
from velora_erp.finance.engine import get_account_balance

from test_cash_transactions import setup_cash, approve, MAKER, APPROVER
from test_invoice_settlement_v271 import _sales_invoice, _purchase_invoice, _receipt, _line

T = date.today()


def _rows(table, **where):
    t = get_table(table)
    with db.transaction() as conn:
        q = select(t)
        for k, v in where.items():
            q = q.where(t.c[k] == v)
        return [dict(r) for r in conn.execute(q).mappings()]


def _cancel(doc, reason="Entered by mistake"):
    with session_as(APPROVER):
        d = get_doc(doc.doctype, doc.name)
        d.cancel(reason=reason)
        d.reload()
    return d


def test_cancelling_a_receipt_removes_its_postings_and_reopens_the_invoice(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        rcpt = approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 400)]))
        inv.reload()
        assert inv.payment_status == "Partly Paid" and get_account_balance(accounts["1000"].name) == Decimal("400")
        batch = rcpt.posting_batch
        done = _cancel(rcpt)
        assert done.docstatus == 2
        assert get_account_balance(accounts["1000"].name) == Decimal("0")             # the cash is gone from the books
        assert _rows("Account Ledger Record", source_doctype="Receipt", source_name=rcpt.name) == []
        assert _rows("Financial Posting Batch", name=batch) == []                      # nothing left to reverse
        inv.reload()
        assert (Decimal(str(inv.amount_settled)), inv.payment_status) == (Decimal("0"), "Unpaid")
        log = _rows("Posting Cancellation Log", source_name=rcpt.name)
        assert len(log) == 1 and log[0]["ledger_rows_removed"] == 2 and log[0]["reason"] == "Entered by mistake"
        assert len(log[0]["snapshot"]["account_ledger"]) == 2                          # evidence of what was removed
    finally:
        velora.shutdown()


def test_cancelling_an_invoice_unlinks_the_receipt_that_settled_it(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        rcpt = approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 1000)]))
        _cancel(inv)                                                                   # not blocked by the receipt
        assert get_account_balance(accounts["4000"].name) == Decimal("0")
        rcpt = get_doc("Receipt", rcpt.name)
        assert rcpt.docstatus == 1 and not rcpt.lines[0].invoice_reference and not rcpt.allocation_status
        # the money is still received, now unapplied on the customer's account
        assert get_account_balance(accounts["1000"].name) == Decimal("1000")
        assert get_account_balance(accounts["1100"].name, party_type="Customer", party=customer.name) == Decimal("-1000")
        assert all(r["source_line_reference"] is None for r in _rows("Account Ledger Record", source_doctype="Receipt", source_name=rcpt.name))
        note = _rows("Posting Cancellation Log", source_name=inv.name)[0]
        assert any("no longer applied" in x for x in note["unlinked"])
    finally:
        velora.shutdown()


def test_amend_after_cancel_posts_the_corrected_version(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        _cancel(inv)
        p = amend.copy_values("Sales Invoice", inv.name, "amend")
        values = dict(p["values"])
        with session_as(MAKER):
            fixed = new_doc("Sales Invoice", **{**values, "lines": [{"description": "Service", "quantity": 1, "rate": 800, "amount": 800, "account": accounts["4000"].name}]}).insert()
        fixed = approve(fixed)
        assert fixed.amended_from == inv.name and fixed.name != inv.name
        assert get_account_balance(accounts["4000"].name) == Decimal("-800")           # only the corrected sale remains
        assert get_account_balance(accounts["1100"].name) == Decimal("800")
    finally:
        velora.shutdown()


def test_a_cancelled_document_cannot_be_cancelled_again_and_its_posting_cannot_be_found_twice(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 500)
        _cancel(inv)
        with session_as(APPROVER):
            with pytest.raises(DocStatusError):
                get_doc("Sales Invoice", inv.name).cancel()
    finally:
        velora.shutdown()


def test_a_closed_period_refuses_the_cancel_and_nothing_changes(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 500)
        periods = get_table("Financial Period")
        from sqlalchemy import update
        with db.transaction() as conn:
            conn.execute(update(periods).values(status="Closed"))
        with session_as(APPROVER):
            with pytest.raises(ValidationError, match="closed"):
                get_doc("Sales Invoice", inv.name).cancel()
        assert get_doc("Sales Invoice", inv.name).docstatus == 1
        assert get_account_balance(accounts["4000"].name) == Decimal("-500")
        assert _rows("Posting Cancellation Log", source_name=inv.name) == []
    finally:
        velora.shutdown()


def test_cancel_needs_the_cancel_permission(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 500)
        with session_as(MAKER):                                                        # an Accountant may prepare, not cancel
            with pytest.raises(PermissionDenied):
                get_doc("Sales Invoice", inv.name).cancel()
        assert get_doc("Sales Invoice", inv.name).docstatus == 1
    finally:
        velora.shutdown()


def test_a_supplier_payment_cancel_reopens_the_purchase_invoice(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _purchase_invoice(accounts, supplier, 900)
        with session_as(MAKER):
            p = new_doc("Payment", payment_date=T, posting_date=T, purpose="Supplier Payment", currency="NGN", exchange_rate=1,
                        cash_account=accounts["1000"].name, narration="Pay supplier",
                        lines=[{"account": accounts["2100"].name, "entry_side": "Debit", "amount": 900, "party_type": "Supplier",
                                "party": supplier.name, "invoice_reference": inv.name, "allocation_amount": 900}]).insert()
        p = approve(p)
        inv.reload(); assert inv.payment_status == "Paid"
        _cancel(p)
        inv.reload()
        assert inv.payment_status == "Unpaid" and get_account_balance(accounts["1000"].name) == Decimal("0")
    finally:
        velora.shutdown()


def test_journal_voucher_cancel_removes_every_row(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            jev = new_doc("Journal Entry Voucher", title="Month-end", voucher_date=T, posting_date=T, currency="NGN", exchange_rate=1, narration="Bulk journal",
                          lines=[{"trans_date": T, "transaction_description": "Bank charge", "account_type": "Account GL", "party": accounts["5000"].name,
                                  "trans_effect": "Debit", "amount": 50, "corresponding_account": accounts["1000"].name}]).insert(ignore_permissions=True)
        jev = approve(jev)
        assert get_account_balance(accounts["5000"].name) == Decimal("50")
        _cancel(jev)
        assert get_account_balance(accounts["5000"].name) == Decimal("0") and get_account_balance(accounts["1000"].name) == Decimal("0")
        assert _rows("Account Ledger Record", source_doctype="Journal Entry Voucher", source_name=jev.name) == []
    finally:
        velora.shutdown()


def test_accrual_cancel_also_removes_its_automatic_reversal(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        accrued = new_doc("Account", account_code="2300", account_name="Accrued Expenses", account_group="L", account_type="DEFERRED_INCOME", allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            accrual = new_doc("Accrual", reporting_date=T, description="Utilities", currency="NGN", exchange_rate=1, auto_reverse=1, reversal_date=T + timedelta(days=1),
                              lines=[{"description": "Utilities incurred", "expense_account": accounts["5000"].name, "accrued_liability_account": accrued.name, "amount": Decimal("1250.00")}]).insert()
        accrual = approve(accrual)
        from velora_erp.finance.doctype.accrual.accrual import process_due_accrual_reversals
        assert accrual.name in process_due_accrual_reversals(T + timedelta(days=1))
        assert get_account_balance(accounts["5000"].name) == Decimal("0")
        done = _cancel(accrual)
        assert done.docstatus == 2 and done.status == "Cancelled" and not done.reversal_batch
        assert _rows("Financial Posting Batch", source_name=accrual.name) == [] and _rows("Account Ledger Record") == []
    finally:
        velora.shutdown()


def test_expense_batch_cancel_clears_the_books_and_the_same_references_can_be_posted_again(tmp_path):
    from test_expense_batch_v271 import _accounts, _batch, _row
    accounts, c, s = setup_cash(tmp_path)
    try:
        petty, wht = _accounts(accounts)
        b = approve(_batch(accounts, petty, wht, [_row(accounts, 1000, wht_rate=5)]))
        assert get_account_balance(petty.name) == Decimal("-950")
        _cancel(b)
        assert get_account_balance(petty.name) == Decimal("0") and get_account_balance(accounts["5000"].name) == Decimal("0")
        again = approve(_batch(accounts, petty, wht, [_row(accounts, 1000, wht_rate=5)]))          # same reference: the cancelled one does not count
        assert get_account_balance(petty.name) == Decimal("-950") and again.docstatus == 1
    finally:
        velora.shutdown()
