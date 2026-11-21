"""Quotation conversion limits and customer credit control."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as
from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from velora_erp.finance.document_flow.conversion import create_document_from

D = lambda v: Decimal(str(v or 0))


def _acct(code):
    return get_list("Account", filters={"account_code": code}, fields=["name"], limit=1)[0]["name"]


def _quote(item, customer, revenue, qty=10, rate=200):
    q = new_doc("Sales Quotation", document_date=date.today(), valid_until=date.today() + timedelta(days=30), party=customer, currency="NGN", exchange_rate=1,
                lines=[{"item_code": item.name, "description": "stock", "quantity": qty, "uom": "Each", "rate": rate}]).insert(ignore_permissions=True)
    return approve_and_submit(q)


def test_quotation_cannot_be_converted_beyond_its_quantity(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            q = _quote(item, customer, revenue)
            first = create_document_from("Sales Quotation", q.name, "Sales Order", {"quantities": {q.lines[0].name: 6}}); first.submit(ignore_permissions=True)
            second = create_document_from("Sales Quotation", q.name, "Sales Order")
            assert D(second.lines[0].quantity) == D(4), "only the unconverted quantity of the quotation may be ordered"
            second.lines[0].quantity = 9
            with pytest.raises(Exception):
                second.save(ignore_permissions=True); second.submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_credit_limit_hold_and_return_relief(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        cust = get_doc("Customer", customer, ignore_permissions=True); cust.credit_limit = 1000; cust.save(ignore_permissions=True)
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 6, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            with pytest.raises(Exception, match="credit limit"):
                so.submit(ignore_permissions=True)          # 1200 > 1000
            so2 = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                          lines=[{"item_code": item.name, "description": "x", "quantity": 5, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so2.submit(ignore_permissions=True)             # exactly 1000 is allowed
            so3 = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                          lines=[{"item_code": item.name, "description": "x", "quantity": 1, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            with pytest.raises(Exception, match="credit limit"):
                so3.submit(ignore_permissions=True)
        cust = get_doc("Customer", customer, ignore_permissions=True); cust.credit_hold = 1; cust.credit_hold_reason = "Overdue"; cust.save(ignore_permissions=True)
        with session_as(MAKER):
            so4 = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                          lines=[{"item_code": item.name, "description": "x", "quantity": 1, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            with pytest.raises(Exception, match="Credit Hold"):
                so4.submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_invoice_cannot_be_edited_beyond_delivered_quantity(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        from test_sales_review_v276 import _stock_in
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier)
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name, "quantities": {so.lines[0].name: 2}}); dn.submit(ignore_permissions=True)
            si = create_document_from("Sales Order", so.name, "Sales Invoice")
            assert D(si.lines[0].quantity) == D(2)
            si.lines[0].quantity = 4; si.lines[0].amount = 800
            with pytest.raises(Exception):
                si.save(ignore_permissions=True); approve_and_submit(si)
    finally:
        velora.shutdown()


def test_order_credit_exposure_includes_tax(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        cust = get_doc("Customer", customer, ignore_permissions=True); cust.credit_limit = 1000; cust.save(ignore_permissions=True)
        tax = get_list("Account", filters={"account_code": "2200"}, fields=["name"], limit=1) or get_list("Account", fields=["name"], filters={"account_type": "TAX_PAYABLE"}, limit=1)
        if not tax:
            pytest.skip("fixture has no tax account")
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "x", "quantity": 5, "uom": "Each", "rate": 190, "revenue_account": revenue, "tax_account": tax[0]["name"], "tax_rate": 7.5}]).insert(ignore_permissions=True)
            with pytest.raises(Exception, match="credit limit"):
                so.submit(ignore_permissions=True)    # 950 + 7.5% = 1021.25 > 1000
    finally:
        velora.shutdown()
