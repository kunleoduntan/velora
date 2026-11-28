"""Cancelling stock documents: the stock ledger rows go, later balances stay true, and stock that later documents used is protected."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

import velora
from velora import db, get_doc, get_list, new_doc
from velora.db.tables import get_table
from velora.exceptions import ValidationError
from velora.permissions import session_as
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.inventory.ledger import get_stock_balance

from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from test_cash_transactions import APPROVER
from test_sales_review_v276 import _balances

D = lambda v: Decimal(str(v or 0))


def _acct(code):
    return get_list("Account", filters={"account_code": code}, fields=["name"], limit=1)[0]["name"]


def _cancel(doctype, name, reason="Wrong"):
    with session_as(APPROVER):
        d = get_doc(doctype, name)
        d.cancel(reason=reason)
        return get_doc(doctype, name)


def _slr(**where):
    t = get_table("Stock Ledger Record")
    with db.transaction() as conn:
        q = select(t)
        for k, v in where.items():
            q = q.where(t.c[k] == v)
        return [dict(r) for r in conn.execute(q.order_by(t.c.creation, t.c.name)).mappings()]


def test_cancelling_a_receipt_removes_stock_and_its_inventory_posting_but_not_while_stock_was_used(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 10, "uom": "Each", "rate": 120}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name}); pr.submit(ignore_permissions=True)
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn.submit(ignore_permissions=True)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 6
        assert D(get_doc("Purchase Order", po.name).per_received) == 100

        # 4 of the 10 have been delivered: the receipt cannot be taken out from under them, and nothing changes
        with pytest.raises(ValidationError, match="would be short by 4"):
            _cancel("Purchase Receipt", pr.name)
        assert get_doc("Purchase Receipt", pr.name).docstatus == 1 and get_stock_balance(item.name, warehouse.name)["qty"] == 6

        # the delivery goes first: stock returns, the order shows nothing delivered, the COGS posting is gone
        _cancel("Delivery Note", dn.name)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 10
        assert _slr(voucher_type="Delivery Note", voucher_no=dn.name) == []
        assert D(get_doc("Sales Order", so.name).per_delivered) == 0
        rows = _slr(item_code=item.name)
        assert len(rows) == 1 and D(rows[0]["qty_after_transaction"]) == 10 and D(rows[0]["stock_value_after_transaction"]) == 1200

        # now the receipt can go, with its GRNI / inventory posting
        _cancel("Purchase Receipt", pr.name)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 0 and _slr() == []
        net, dr, cr = _balances()
        assert dr == cr == 0 and not any(net.values())
        assert D(get_doc("Purchase Order", po.name).per_received) == 0
        log = [r for r in get_list("Posting Cancellation Log", filters={"source_name": pr.name}, fields=["stock_rows_removed", "ledger_rows_removed"], limit=5, ignore_permissions=True)]
        assert log and log[0]["stock_rows_removed"] == 1 and log[0]["ledger_rows_removed"] == 2
    finally:
        velora.shutdown()


def test_cancel_all_walks_the_chain_and_later_running_balances_are_recomputed(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            for qty in (10, 5):                                                    # two receipts, second one cancelled later
                po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                             lines=[{"item_code": item.name, "description": "stock", "quantity": qty, "uom": "Each", "rate": 100}]).insert(ignore_permissions=True)
                po.submit(ignore_permissions=True)
                pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name}); pr.submit(ignore_permissions=True)
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 3, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn.submit(ignore_permissions=True)
        first_rows = _slr(item_code=item.name)
        assert [D(r["qty_after_transaction"]) for r in first_rows] == [10, 15, 12]
        _cancel("Purchase Receipt", pr.name)                                         # the second receipt: 12 -> 7 still fine
        rows = _slr(item_code=item.name)
        assert [D(r["qty_after_transaction"]) for r in rows] == [10, 7]
        assert [D(r["stock_value_after_transaction"]) for r in rows] == [1000, 700]
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 7
        # the sales order cannot be cancelled while its delivery stands; "cancel all" does both, delivery first
        from velora import linked
        with session_as(APPROVER):
            blockers = linked.submitted_dependents("Sales Order", so.name)
            assert [b["doctype"] for b in blockers] == ["Delivery Note"]
            linked.cancel_all("Sales Order", so.name, "Customer changed mind")
        assert get_doc("Sales Order", so.name).docstatus == 2 and get_doc("Delivery Note", dn.name).docstatus == 2
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 10
    finally:
        velora.shutdown()


def test_sales_invoice_with_update_stock_cancel_returns_the_stock_and_cogs_and_a_sales_return_blocks_it(tmp_path):
    from test_sales_review_v276 import _stock_in, _direct_sale
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier)
            inv = _direct_sale(item, customer, revenue, warehouse, True).insert(ignore_permissions=True)
        approve_and_submit(inv)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 7
        with session_as(MAKER):
            sr = create_document_from("Sales Invoice", inv.name, "Sales Return", {"warehouse": warehouse.name, "quantities": {inv.lines[0].name: 1}})
        sr = approve_and_submit(sr)
        # the return points at the invoice, so the invoice cannot be cancelled on its own
        from velora import linked
        with session_as(APPROVER):
            assert [b["doctype"] for b in linked.submitted_dependents("Sales Invoice", inv.name)] == ["Sales Return"]
            with pytest.raises(ValidationError, match="Sales Return"):
                get_doc("Sales Invoice", inv.name).cancel()
            linked.cancel_all("Sales Invoice", inv.name, "Entered twice")
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 10
        net, dr, cr = _balances()
        assert dr == cr and not net.get(cogs.name) and not net.get(revenue)
        assert net[inventory.name] == D(1200)                                      # only the purchase receipt remains
    finally:
        velora.shutdown()
