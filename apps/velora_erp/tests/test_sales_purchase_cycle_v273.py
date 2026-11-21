"""End-to-end procure-to-pay and order-to-cash cycle: the general ledger must agree with the stock ledger and with the documents."""
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


def test_full_cycle_ledger_agrees_with_stock_and_documents(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        revenue, expense = _acct("4000"), _acct("5000")
        # ---- procure: 10 @ 100, receive, invoice from the receipt
        with session_as(MAKER):
            po = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 10, "uom": "Each", "rate": 100}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            pr = create_document_from("Purchase Order", po.name, "Purchase Receipt", {"warehouse": warehouse.name}); pr.submit(ignore_permissions=True)
            pr = get_doc("Purchase Receipt", pr.name)
            pi = create_document_from("Purchase Receipt", pr.name, "Purchase Invoice"); pi.lines[0].account = expense; pi.save(ignore_permissions=True)
        pi = approve_and_submit(pi)
        net, dr, cr = _balances()
        assert net[inventory.name] == D(1000) and net.get(grni.name, 0) == 0 and net[_acct("2100")] == D(-1000)
        # ---- sell 4 @ 150: deliver, invoice from the order
        with session_as(MAKER):
            so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                         lines=[{"item_code": item.name, "description": "stock", "quantity": 4, "uom": "Each", "rate": 150, "revenue_account": revenue}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            dn = create_document_from("Sales Order", so.name, "Delivery Note", {"warehouse": warehouse.name}); dn.submit(ignore_permissions=True)
            si = create_document_from("Sales Order", so.name, "Sales Invoice")
        si = approve_and_submit(si)
        net, dr, cr = _balances()
        assert get_stock_balance(item.name, warehouse.name)["qty"] == D(6)
        assert net[cogs.name] == D(400), "COGS must equal cost of the 4 delivered units"
        assert net[inventory.name] == D(600)
        assert net[revenue] == D(-600) and net[_acct("1100")] == D(600)
        # ---- returns: customer returns 1, we return 2 to the supplier
        with session_as(MAKER):
            sr = create_document_from("Sales Invoice", si.name, "Sales Return", {"warehouse": warehouse.name, "quantities": {si.lines[0].name: 1}})
        approve_and_submit(sr)
        with session_as(MAKER):
            pret = create_document_from("Purchase Invoice", pi.name, "Purchase Return", {"warehouse": warehouse.name, "quantities": {pi.lines[0].name: 2}})
        approve_and_submit(pret)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert stock["qty"] == D(5) and stock["value"] == D(500)
        assert net[inventory.name] == stock["value"], "GL inventory must equal the stock ledger valuation"
        assert net.get(grni.name, 0) == 0
        assert net[cogs.name] == D(300) and net[revenue] == D(-450)
        assert net[_acct("1100")] == D(450) and net[_acct("2100")] == D(-800)
        assert dr == cr, "the ledger must balance"
    finally:
        velora.shutdown()


def _direct_invoice(item, warehouse, supplier, update_stock):
    return new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                   narration="Direct stock invoice", update_stock=1 if update_stock else 0, warehouse=warehouse.name if update_stock else None,
                   lines=[{"item_code": item.name, "quantity": 2, "uom": "Each", "account": _acct("5000"), "description": "stock", "amount": 200}])


def test_invoice_without_receipt_with_update_stock_receives_the_goods(tmp_path):
    """Like ERPNext: a receipt is optional; Update Stock makes the invoice itself receive the goods into inventory."""
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        with session_as(MAKER):
            inv = _direct_invoice(item, warehouse, supplier, True).insert(ignore_permissions=True)
        approve_and_submit(inv)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert stock["qty"] == D(2) and stock["value"] == D(200)
        assert net[inventory.name] == D(200) == stock["value"] and net.get(grni.name, 0) == 0
        assert net[_acct("2100")] == D(-200) and dr == cr
        # returning one unit at cost credits the item's inventory account, not GRNI or expense
        with session_as(MAKER):
            ret = create_document_from("Purchase Invoice", inv.name, "Purchase Return", {"warehouse": warehouse.name, "quantities": {inv.lines[0].name: 1}})
        approve_and_submit(ret)
        net, dr, cr = _balances()
        stock = get_stock_balance(item.name, warehouse.name)
        assert stock["qty"] == D(1) and net[inventory.name] == stock["value"] == D(100)
        assert net.get(grni.name, 0) == 0 and dr == cr
    finally:
        velora.shutdown()


def test_inventory_settings_can_make_the_receipt_compulsory(tmp_path):
    import pytest
    from velora.exceptions import ValidationError
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
        settings = get_doc("Inventory Settings", get_list("Inventory Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
        settings.require_purchase_receipt_for_stock_invoices = 1
        settings.save(ignore_permissions=True)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match="Purchase Receipt"):
                _direct_invoice(item, warehouse, supplier, True).insert(ignore_permissions=True)
    finally:
        velora.shutdown()
