from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import session_as
from velora_erp.finance.engine import get_account_balance
from velora_erp.finance.invoice_settlement import suggest_allocations, build_lines_from_allocations, outstanding_invoices
from test_cash_transactions import setup_cash, approve, MAKER, APPROVER

T = date.today()


def _sales_invoice(accounts, customer, amount, due_days=30, narration="Sale"):
    with session_as(MAKER):
        inv = new_doc("Sales Invoice", invoice_date=T, posting_date=T, due_date=T + timedelta(days=due_days), party=customer.name,
                      currency="NGN", exchange_rate=1, narration=narration,
                      lines=[{"description": "Service", "quantity": 1, "rate": amount, "amount": amount, "account": accounts["4000"].name}]).insert()
    return approve(inv)


def _purchase_invoice(accounts, supplier, amount, due_days=30):
    with session_as(MAKER):
        inv = new_doc("Purchase Invoice", invoice_date=T, posting_date=T, due_date=T + timedelta(days=due_days), party=supplier.name,
                      currency="NGN", exchange_rate=1, narration="Purchase",
                      lines=[{"description": "Stationery", "quantity": 1, "amount": amount, "account": accounts["5000"].name}]).insert()
    return approve(inv)


def _receipt(accounts, customer, lines, narration="Settlement"):
    with session_as(MAKER):
        return new_doc("Receipt", receipt_date=T, posting_date=T, purpose="Customer Receipt", currency="NGN", exchange_rate=1,
                       cash_account=accounts["1000"].name, narration=narration, lines=lines).insert()


def _line(accounts, customer, invoice, amount, alloc=None):
    return {"account": accounts["1100"].name, "entry_side": "Credit", "amount": amount, "party_type": "Customer", "party": customer.name,
            "invoice_reference": invoice.name, "allocation_amount": amount if alloc is None else alloc}


def test_partial_then_full_settlement_tracks_outstanding(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        assert inv.payment_status == "Unpaid"
        approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 400)]))
        inv.reload(); assert (Decimal(str(inv.amount_settled)), inv.payment_status) == (Decimal("400"), "Partly Paid")
        with pytest.raises(ValidationError, match="only 600.00 outstanding"):
            _receipt(accounts, customer, [_line(accounts, customer, inv, 700)])
        approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 600)]))
        inv.reload(); assert (Decimal(str(inv.amount_settled)), inv.payment_status) == (Decimal("1000"), "Paid")
        with pytest.raises(ValidationError, match="outstanding"):
            _receipt(accounts, customer, [_line(accounts, customer, inv, 1)])
    finally:
        velora.shutdown()


def test_concurrent_drafts_cannot_over_settle(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        r1 = _receipt(accounts, customer, [_line(accounts, customer, inv, 800)])
        r2 = _receipt(accounts, customer, [_line(accounts, customer, inv, 800)])
        approve(r1)
        with pytest.raises(ValidationError, match="outstanding"):
            approve(r2)
        inv.reload(); assert Decimal(str(inv.amount_settled)) == Decimal("800")
        assert get_account_balance(accounts["1000"].name) == Decimal("800.000000")
    finally:
        velora.shutdown()


def test_multi_invoice_discount_wht_and_unapplied_advance(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        wht = new_doc("Account", account_code="1300", account_name="WHT Receivable", account_group="A", account_type="CLEARING", allow_manual_posting=1).insert(ignore_permissions=True)
        disc = new_doc("Account", account_code="5100", account_name="Discount Allowed", account_group="X", account_type="OPERATING_EXPENSE", allow_manual_posting=1).insert(ignore_permissions=True)
        a = _sales_invoice(accounts, customer, 1000, 10); b = _sales_invoice(accounts, customer, 500, 20)
        lines = [_line(accounts, customer, a, 1000), _line(accounts, customer, b, 500),
                 {"account": wht.name, "entry_side": "Debit", "amount": 75, "description": "WHT deducted"},
                 {"account": disc.name, "entry_side": "Debit", "amount": 25, "description": "Early payment discount"},
                 {"account": accounts["1100"].name, "entry_side": "Credit", "amount": 100, "party_type": "Customer", "party": customer.name, "description": "Unapplied cash on account"}]
        r = approve(_receipt(accounts, customer, lines))
        assert r.total_amount == Decimal("1500")          # 1000+500+100 credits - 75 - 25 debits
        assert get_account_balance(accounts["1000"].name) == Decimal("1500.000000")
        for inv in (a, b):
            inv.reload(); assert inv.payment_status == "Paid"
        assert r.allocation_status == "Applied"
    finally:
        velora.shutdown()


def test_wrong_party_and_unsupported_purpose_are_rejected(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        other = new_doc("Customer", customer_code="C002", customer_name="Other", customer_group="CG", customer_type="Company",
                        control_account=accounts["1100"].name, advance_account=accounts["2200"].name).insert(ignore_permissions=True)
        inv = _sales_invoice(accounts, customer, 100)
        bad = _line(accounts, other, inv, 50)
        with pytest.raises(ValidationError, match="belongs to"):
            _receipt(accounts, customer, [bad])
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="cannot be settled by a Other Income"):
                new_doc("Receipt", receipt_date=T, posting_date=T, purpose="Other Income", currency="NGN", exchange_rate=1,
                        cash_account=accounts["1000"].name, narration="x",
                        lines=[{"account": accounts["4000"].name, "amount": 10, "invoice_reference": inv.name, "allocation_amount": 10}]).insert()
    finally:
        velora.shutdown()


def test_fifo_suggestion_and_line_builder(tmp_path):
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        late = _sales_invoice(accounts, customer, 300, 40); early = _sales_invoice(accounts, customer, 200, 5)
        s = suggest_allocations("Customer", customer.name, 600)
        assert [x["invoice"] for x in s["allocations"]] == [early.name, late.name]
        assert s["allocated"] == Decimal("500") and s["unapplied"] == Decimal("100")
        lines = build_lines_from_allocations("Customer", customer.name, accounts["1100"].name, s["allocations"],
                                             unapplied=s["unapplied"])
        r = approve(_receipt(accounts, customer, lines))
        assert r.total_amount == Decimal("600") and outstanding_invoices("Customer", customer.name) == []
    finally:
        velora.shutdown()


def test_backfill_patch_rebuilds_settlement_and_skips_cancelled(tmp_path):
    from sqlalchemy import update
    from velora import db
    from velora.db.tables import get_table
    from velora_erp.patches.v2_71 import backfill_invoice_settlement
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        inv = _sales_invoice(accounts, customer, 1000)
        r1 = approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 300)]))
        r2 = approve(_receipt(accounts, customer, [_line(accounts, customer, inv, 200)]))
        with session_as(APPROVER):
            get_doc("Receipt", r2.name).cancel(reason="duplicate")
        t = get_table("Sales Invoice")
        with db.transaction() as conn:
            conn.execute(update(t).where(t.c.name == inv.name).values(amount_settled=0, payment_status="Unpaid"))
        with db.transaction():
            backfill_invoice_settlement.execute()
        inv.reload(); assert (Decimal(str(inv.amount_settled)), inv.payment_status) == (Decimal("300"), "Partly Paid")
    finally:
        velora.shutdown()


def test_apply_to_invoices_endpoint_builds_receipt_lines_that_settle_the_chosen_invoices(tmp_path):
    from velora_erp.finance.document_flow.api import settlement_outstanding, settlement_allocate
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        a = _sales_invoice(accounts, customer, 300, due_days=10)
        b = _sales_invoice(accounts, customer, 500, due_days=20)
        out = settlement_outstanding({"party_type": "Customer", "party": customer.name})
        assert [r["invoice"] for r in out["invoices"]] == [a.name, b.name] and "Best Match" in out["methods"]
        auto = settlement_allocate({"party_type": "Customer", "party": customer.name, "amount": 500, "method": "Best Match"})
        assert [x["invoice"] for x in auto["allocations"]] == [b.name]  # exactly clears the 500 invoice
        # the user overrides by hand: 100 to the first, 150 to the second, 50 left as an advance
        manual = settlement_allocate({"party_type": "Customer", "party": customer.name, "amount": 300,
                                      "allocations": [{"invoice": a.name, "allocate": 100}, {"invoice": b.name, "allocate": 150}]})
        assert Decimal(str(manual["unapplied"])) == Decimal(50)
        with pytest.raises(ValidationError):
            settlement_allocate({"party_type": "Customer", "party": customer.name, "amount": 900, "allocations": [{"invoice": a.name, "allocate": 400}]})
        with session_as(MAKER):
            rcpt = new_doc("Receipt", receipt_date=T, posting_date=T, purpose="Customer Receipt", currency="NGN", exchange_rate=1, cash_account=accounts["1000"].name,
                           narration="Applied", lines=manual["lines"]).insert()
        approve(rcpt)
        a.reload(); b.reload()
        assert Decimal(str(a.amount_settled)) == 100 and Decimal(str(b.amount_settled)) == 150
    finally:
        velora.shutdown()
