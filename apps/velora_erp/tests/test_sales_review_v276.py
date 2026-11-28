"""Sales review: returns restock at the original issue cost; invoices can deliver stock themselves (Update Stock)."""
from datetime import date
from decimal import Decimal
import velora
from velora import get_doc, get_list, new_doc
from velora.permissions import session_as
from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.inventory.ledger import get_stock_balance

D = lambda v: Decimal(str(v or 0))


def _balances():
    rows = get_list("Account Ledger Record", fields=["account", "debit", "credit"], limit=5000)
    net = {}
    for r in rows:
        net[r["account"]] = net.get(r["account"], Decimal(0)) + D(r["debit"]) - D(r["credit"])
    return net, sum(D(r["debit"]) for r in rows), sum(D(r["credit"]) for r in rows)


def _acct(code):
    return get_list("Account", filters={"account_code": code}, fields=["name"], limit=1)[0]["name"]


def test_sales_return_restocks_at_original_issue_cost(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)  # standard_rate is 100
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue, expense = _acct("4000"), _acct("5000")
        with session_as(MAKER):
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 10, "uom": "Each", "rate": 120}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name}); pr.submit(ignore_permissions=True)
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn.submit(ignore_permissions=True)
            si = create_document_from("Sales Order", so.name, "Sales Invoice")
        si = approve_and_submit(si)
        net, dr, cr = _balances()
        assert net[cogs.name] == D(480)
        with session_as(MAKER):
            sr = create_document_from("Sales Invoice", si.name, "Sales Return", {"warehouse": warehouse.name, "quantities": {si.lines[0].name: 1}})
        approve_and_submit(sr)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert net[cogs.name] == D(360), "return must reverse COGS at the original cost of 120, not the standard rate"
        assert net[inventory.name] == stock["value"] and dr == cr
    finally:
        velora.shutdown()


def _stock_in(item, warehouse, supplier, qty=10, rate=120):
    po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                 lines=[{"item_code": item.name, "description": "stock", "quantity": qty, "uom": "Each", "rate": rate}]).insert(ignore_permissions=True)
    po.submit(ignore_permissions=True)
    pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name}); pr.submit(ignore_permissions=True)


def _direct_sale(item, customer, revenue, warehouse, update_stock):
    return new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                   update_stock=1 if update_stock else 0, warehouse=warehouse.name if update_stock else None, narration="Direct sale",
                   lines=[{"item_code": item.name, "quantity": 3, "uom": "Each", "account": revenue, "description": "stock", "amount": 600, "rate": 200}])


def test_sales_invoice_update_stock_delivers_and_posts_cogs(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier)
            inv = _direct_sale(item, customer, revenue, warehouse, True).insert(ignore_permissions=True)
        approve_and_submit(inv)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert stock["qty"] == D(7) and net[cogs.name] == D(360)
        assert net[inventory.name] == stock["value"] == D(840) and net[revenue] == D(-600) and dr == cr
        inv = get_doc("Sales Invoice", inv.name)
        assert D(inv.lines[0].valuation_rate) == D(120), "the invoice line records the cost it issued at"
        with session_as(MAKER):
            sr = create_document_from("Sales Invoice", inv.name, "Sales Return", {"warehouse": warehouse.name, "quantities": {inv.lines[0].name: 1}})
        approve_and_submit(sr)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert net[cogs.name] == D(240) and net[inventory.name] == stock["value"] == D(960) and dr == cr
    finally:
        velora.shutdown()


def test_sales_invoice_without_update_stock_leaves_stock_alone_and_order_invoices_refuse_it(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier)
            inv = _direct_sale(item, customer, revenue, warehouse, False).insert(ignore_permissions=True)
        approve_and_submit(inv)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == D(10)
        # update stock on an order-sourced invoice would post COGS twice (the delivery note already did)
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 1, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn.submit(ignore_permissions=True)
            si = create_document_from("Sales Order", so.name, "Sales Invoice")
            si.update_stock = 1; si.warehouse = warehouse.name
            try:
                si.save(ignore_permissions=True); refused = False
            except Exception as exc:
                refused = "twice" in str(exc)
        assert refused
    finally:
        velora.shutdown()


def test_orders_cannot_be_over_delivered_over_received_or_invoiced_beyond_delivery(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue = _acct("4000")
        with session_as(MAKER):
            _stock_in(item, warehouse, supplier, qty=20)
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 5, "uom": "Each", "rate": 120}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name, "quantities": {po.lines[0].name: 3}}); pr.submit(ignore_permissions=True)
            pr2 = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name})
            assert D(pr2.lines[0].quantity) == D(2), "only the remaining ordered quantity may be received"
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name, "quantities": {so.lines[0].name: 1}}); dn.submit(ignore_permissions=True)
            si = create_document_from("Sales Order", so.name, "Sales Invoice")
            assert D(si.lines[0].quantity) == D(1), "an order is invoiced only up to what has been delivered"
            dn2 = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name})
            assert D(dn2.lines[0].quantity) == D(3)
            dn2.lines[0].quantity = 9
            try:
                dn2.save(ignore_permissions=True); dn2.submit(ignore_permissions=True); over = False
            except Exception:
                over = True
        assert over, "delivering more than ordered must be refused"
    finally:
        velora.shutdown()
