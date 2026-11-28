"""Create-from across sales and purchase documents, and Pay buttons backed by outstanding-aware settlement."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as
from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from test_sales_review_v276 import _stock_in, _balances
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.inventory.ledger import get_stock_balance

D = lambda v: Decimal(str(v or 0))


def _acct(code):
    return get_list("Account", filters={"account_code": code}, fields=["name"], limit=1)[0]["name"]


def test_invoice_from_delivery_waybill_and_quotation_and_purchase_invoice_from_order(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue, expense = _acct("4000"), _acct("5000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier, qty=10, rate=120)
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn1 = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name, "quantities": {so.lines[0].name: 1}}); dn1.submit(ignore_permissions=True)
            dn2 = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn2.submit(ignore_permissions=True)
            wb = create_document_from("Delivery Note", dn2.name, "Waybill"); wb.submit(ignore_permissions=True)
            inv1 = create_document_from("Delivery Note", dn1.name, "Sales Invoice")
            assert D(inv1.lines[0].quantity) == 1 and inv1.source_document == so.name
        approve_and_submit(inv1)
        with session_as(MAKER):
            inv2 = create_document_from("Waybill", wb.name, "Sales Invoice")
            assert D(inv2.lines[0].quantity) == 3
        approve_and_submit(inv2)
        with session_as(MAKER):
            with pytest.raises(Exception, match="No billable"):
                create_document_from("Delivery Note", dn1.name, "Sales Invoice")
        # quotation straight to invoice: part ordered first, the rest invoiced with Update Stock
        with session_as(MAKER):
            q = new_doc("Sales Quotation", document_date=date.today(), valid_until=date.today() + timedelta(days=10), party=customer, currency="NGN", exchange_rate=1,
                        lines=[{"item_code": item.name, "description": "x", "quantity": 5, "uom": "Each", "rate": 200}]).insert(ignore_permissions=True)
        q = approve_and_submit(q)
        with session_as(MAKER):
            o = create_document_from("Sales Quotation", q.name, "Sales Order", {"quantities": {q.lines[0].name: 2}})
            with pytest.raises(Exception, match="Dispatch Warehouse"):
                create_document_from("Sales Quotation", q.name, "Sales Invoice", {"revenue_account": revenue})
            qi = create_document_from("Sales Quotation", q.name, "Sales Invoice", {"revenue_account": revenue, "warehouse": warehouse.name})
        assert D(qi.lines[0].quantity) == 3 and qi.update_stock == 1
        before = get_stock_balance(item.name, warehouse.name)["qty"]
        approve_and_submit(qi)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == before - 3
        with session_as(MAKER):
            with pytest.raises(Exception, match="already been ordered or invoiced"):
                create_document_from("Sales Quotation", q.name, "Sales Invoice", {"revenue_account": revenue, "warehouse": warehouse.name})
        # purchase invoice straight from a purchase order: 2 received, the other 3 invoiced with Update Stock
        with session_as(MAKER):
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 5, "uom": "Each", "rate": 130}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name, "quantities": {po.lines[0].name: 2}}); pr.submit(ignore_permissions=True)
            with pytest.raises(Exception, match="Warehouse"):
                create_document_from("Purchase Order", po.name, "Purchase Invoice", {"expense_account": expense})
            pinv = create_document_from("Purchase Order", po.name, "Purchase Invoice", {"expense_account": expense, "warehouse": warehouse.name})
        assert D(pinv.lines[0].quantity) == 3 and D(pinv.net_amount) == 390 and pinv.update_stock == 1
        before = get_stock_balance(item.name, warehouse.name)["qty"]
        approve_and_submit(pinv)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == before + 3
        net, dr, cr = _balances()
        assert dr == cr
    finally:
        velora.shutdown()


def test_pay_buttons_propose_the_outstanding_balance_and_advances_use_the_advance_account(tmp_path):
    from test_cash_transactions import setup_cash, approve
    accounts, customer, supplier = setup_cash(tmp_path)
    try:
        bank = new_doc("Bank Account", account_code="GTB-1", account_name="GTB", gl_account=accounts["1000"].name, currency="NGN").insert(ignore_permissions=True)
        with session_as(MAKER):
            si = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1, narration="Sale",
                         lines=[{"account": accounts["4000"].name, "description": "Service", "quantity": 1, "uom": "Each", "amount": 1000}]).insert(ignore_permissions=True)
        si = approve(si)
        with session_as(MAKER):
            r1 = create_document_from("Sales Invoice", si.name, "Receipt", {"bank_account": bank.name, "settlement_amount": 400})
            with pytest.raises(Exception, match="cannot exceed|nothing left"):
                create_document_from("Sales Invoice", si.name, "Receipt", {"bank_account": bank.name, "settlement_amount": 700})
        approve(r1)
        with session_as(MAKER):
            r2 = create_document_from("Sales Invoice", si.name, "Receipt", {"bank_account": bank.name})
        assert D(r2.lines[0].amount) == 600, "the second receipt proposes what is still outstanding"
        # advance against a sales order and a purchase order
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1,
                         lines=[{"description": "Retainer", "quantity": 2, "uom": "Each", "rate": 500, "revenue_account": accounts["4000"].name}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            adv = create_document_from("Sales Order", so.name, "Receipt", {"bank_account": bank.name, "settlement_amount": 300})
        assert adv.purpose == "Customer Advance" and adv.lines[0].account == customer.advance_account and D(adv.lines[0].amount) == 300
        approve(adv)
        with session_as(MAKER):
            again = create_document_from("Sales Order", so.name, "Receipt", {"bank_account": bank.name})
        assert D(again.lines[0].amount) == 700, "advances already received reduce what can still be requested"
        with session_as(MAKER):
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                         lines=[{"description": "Consulting", "quantity": 1, "uom": "Each", "rate": 800}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pay = create_document_from("Purchase Order", po.name, "Payment", {"bank_account": bank.name, "settlement_amount": 200})
        assert pay.purpose == "Supplier Advance" and pay.lines[0].account == supplier.advance_account
    finally:
        velora.shutdown()
