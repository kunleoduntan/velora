"""Get Items From and fulfilment: Purchase Order -> Purchase Receipt -> Purchase Invoice, and Sales Order -> Delivery Note -> Sales Invoice."""
from datetime import date

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as

from test_inventory_v012 import setup_inventory
from velora_erp.finance.document_flow import pull

BOSS = Session("boss@example.test", frozenset({"System Manager", "Accountant", "Finance Manager"}))


def _po(supplier, qty, rate=100, item="ITEM-STOCK-1"):
    po = new_doc("Purchase Order", document_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                 lines=[{"item_code": item, "description": "Paper", "quantity": qty, "uom": "Each", "rate": rate, "warehouse": "Main Store"}]).insert()
    po.submit()
    return get_doc("Purchase Order", po.name)


def _make(target, source, names, **extra):
    got = pull.pull(target, source, names)
    return new_doc(target, **({"document_date": date.today()} if target in ("Purchase Receipt", "Delivery Note") else {}),
                   **got["header"], lines=got["lines"], **extra), got


def test_a_receipt_can_stand_alone_or_merge_several_orders_and_the_orders_show_fulfilment(tmp_path):
    setup_inventory(tmp_path)
    from velora import get_list
    supplier = get_doc('Supplier', get_list('Supplier', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    customer = get_doc('Customer', get_list('Customer', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    expense = get_doc('Account', get_list('Account', filters={'account_code': '5000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    revenue = get_doc('Account', get_list('Account', filters={'account_code': '4000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    try:
        with session_as(BOSS):
            standalone = new_doc("Purchase Receipt", document_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                                 lines=[{"item_code": "ITEM-STOCK-1", "quantity": 3, "uom": "Each", "valuation_rate": 50}], warehouse="Main Store").insert()
            assert standalone.lines[0].description                                      # the item supplies it, like ERPNext
            po1, po2 = _po(supplier, 10), _po(supplier, 5)
            assert [c["name"] for c in pull.candidates("Purchase Receipt", "Purchase Order", supplier.name)] == [po2.name, po1.name]
            receipt, got = _make("Purchase Receipt", "Purchase Order", [po1.name, po2.name])
            assert len(got["lines"]) == 2 and {l["source_document"] for l in got["lines"]} == {po1.name, po2.name}
            receipt.insert(); receipt.submit()
            for po in (po1, po2):
                fresh = get_doc("Purchase Order", po.name)
                assert float(fresh.per_received) == 100 and float(fresh.per_billed) == 0 and fresh.document_status == "Partially Processed"
            with pytest.raises(ValidationError, match="Nothing is left"):
                pull.pull("Purchase Receipt", "Purchase Order", [po1.name])
            over = new_doc("Purchase Receipt", document_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                           warehouse="Main Store", lines=[{"item_code": "ITEM-STOCK-1", "quantity": 1, "uom": "Each", "valuation_rate": 100, "source_doctype": "Purchase Order",
                                   "source_document": po1.name, "source_line": po1.lines[0].name}])
            with pytest.raises(ValidationError, match="exceed"):
                over.insert()
    finally:
        velora.shutdown()


def test_merged_receipts_are_invoiced_together_and_the_orders_become_completed(tmp_path):
    setup_inventory(tmp_path)
    from velora import get_list
    supplier = get_doc('Supplier', get_list('Supplier', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    customer = get_doc('Customer', get_list('Customer', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    expense = get_doc('Account', get_list('Account', filters={'account_code': '5000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    revenue = get_doc('Account', get_list('Account', filters={'account_code': '4000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    try:
        with session_as(BOSS):
            po1, po2 = _po(supplier, 10), _po(supplier, 5)
            r1, _ = _make("Purchase Receipt", "Purchase Order", [po1.name]); r1.insert(); r1.submit()
            r2, _ = _make("Purchase Receipt", "Purchase Order", [po2.name]); r2.insert(); r2.submit()
            cands = pull.candidates("Purchase Invoice", "Purchase Receipt", supplier.name)
            assert {c["name"] for c in cands} == {r1.name, r2.name}
            invoice, got = _make("Purchase Invoice", "Purchase Receipt", [r1.name, r2.name], invoice_date=date.today(), posting_date=date.today(), due_date=date.today())
            assert {l["purchase_receipt"] for l in got["lines"]} == {r1.name, r2.name}
            for l in invoice.lines:
                l.account = expense.name
            invoice.insert(); invoice.submit()
            for po in (po1, po2):
                fresh = get_doc("Purchase Order", po.name)
                assert float(fresh.per_billed) == 100 and fresh.document_status == "Completed"
            assert float(get_doc("Purchase Receipt", r1.name).per_billed) == 100
            with pytest.raises(ValidationError, match="Nothing is left"):
                pull.pull("Purchase Invoice", "Purchase Receipt", [r1.name])
    finally:
        velora.shutdown()


def test_orders_can_be_invoiced_together_without_a_receipt(tmp_path):
    setup_inventory(tmp_path)
    from velora import get_list
    supplier = get_doc('Supplier', get_list('Supplier', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    customer = get_doc('Customer', get_list('Customer', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    expense = get_doc('Account', get_list('Account', filters={'account_code': '5000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    revenue = get_doc('Account', get_list('Account', filters={'account_code': '4000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    try:
        with session_as(BOSS):
            po1, po2 = _po(supplier, 4), _po(supplier, 6)
            invoice, got = _make("Purchase Invoice", "Purchase Order", [po1.name, po2.name], invoice_date=date.today(), posting_date=date.today(), due_date=date.today())
            for l in invoice.lines:
                l.account = expense.name
            invoice.insert(); invoice.submit()
            assert float(get_doc("Purchase Order", po1.name).per_billed) == 100
            assert get_doc("Purchase Order", po2.name).document_status == "Completed"
            more = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1,
                           lines=[{"item_code": "ITEM-STOCK-1", "description": "x", "quantity": 1, "uom": "Each", "rate": 100, "amount": 100, "account": expense.name,
                                   "source_doctype": "Purchase Order", "source_document": po1.name, "source_line": po1.lines[0].name}])
            with pytest.raises(ValidationError, match="exceed"):
                more.insert()
    finally:
        velora.shutdown()


def test_deliveries_merge_orders_and_a_hand_made_delivery_can_be_invoiced(tmp_path):
    setup_inventory(tmp_path)
    from velora import get_list
    supplier = get_doc('Supplier', get_list('Supplier', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    customer = get_doc('Customer', get_list('Customer', fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    expense = get_doc('Account', get_list('Account', filters={'account_code': '5000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    revenue = get_doc('Account', get_list('Account', filters={'account_code': '4000'}, fields=['name'], limit=1, ignore_permissions=True)[0]['name'], ignore_permissions=True)
    try:
        with session_as(BOSS):
            def so(qty):
                o = new_doc("Sales Order", document_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1,
                            lines=[{"item_code": "ITEM-002", "description": "Desk", "quantity": qty, "uom": "Each", "rate": 100, "revenue_account": revenue.name}]).insert()
                o.submit(); return get_doc("Sales Order", o.name)
            so1, so2 = so(2), so(3)
            dn, got = _make("Delivery Note", "Sales Order", [so1.name, so2.name]); dn.insert(); dn.submit()
            for o in (so1, so2):
                fresh = get_doc("Sales Order", o.name)
                assert float(fresh.per_delivered) == 100 and fresh.document_status == "Partially Processed"
            from velora_erp.finance.document_flow.conversion import create_document_from
            inv = create_document_from("Delivery Note", dn.name, "Sales Invoice", {})
            assert {l.source_document for l in inv.lines} == {so1.name, so2.name}
            inv.submit()
            assert float(get_doc("Delivery Note", dn.name).per_billed) == 100
            assert get_doc("Sales Order", so1.name).document_status == "Completed"
            # a delivery typed in by hand, with no order at all, can still be invoiced from
            hand = new_doc("Delivery Note", document_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1,
                           lines=[{"item_code": "ITEM-001", "quantity": 2, "uom": "Each", "rate": 50}]).insert()
            hand.submit()
            item = get_doc("Inventory Item", "ITEM-001", ignore_permissions=True); item.income_account = revenue.name; item.save(ignore_permissions=True)
            inv2 = create_document_from("Delivery Note", hand.name, "Sales Invoice", {})
            assert inv2.lines[0].source_doctype == "Delivery Note" and float(inv2.lines[0].quantity) == 2
            inv2.submit()
            assert float(get_doc("Delivery Note", hand.name).per_billed) == 100
    finally:
        velora.shutdown()


def test_the_upgrade_patch_fills_in_fulfilment_for_existing_orders(tmp_path):
    setup_inventory(tmp_path)
    from velora import get_list
    from velora_erp.patches.v2_87 import compute_order_fulfilment
    try:
        with session_as(BOSS):
            supplier = get_doc("Supplier", get_list("Supplier", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
            po = _po(supplier, 10)
            r, _ = _make("Purchase Receipt", "Purchase Order", [po.name]); r.insert(); r.submit()
            from velora import db
            from velora.db.tables import get_table
            from sqlalchemy import update
            with db.transaction() as c:                                     # as an old company would have it: nothing computed
                c.execute(update(get_table("Purchase Order")).values(per_received=0, document_status="Open"))
            compute_order_fulfilment.execute()
            assert float(get_doc("Purchase Order", po.name).per_received) == 100
    finally:
        velora.shutdown()


def test_get_items_from_rest_api(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    setup_inventory(tmp_path)
    from velora import get_list
    try:
        with session_as(BOSS):
            supplier = get_doc("Supplier", get_list("Supplier", fields=["name"], limit=1, ignore_permissions=True)[0]["name"], ignore_permissions=True)
            po = _po(supplier, 7)
        client = TestClient(create_app(auto_init=False))
        h = {"X-Velora-User": BOSS.user, "X-Velora-Roles": "System Manager,Accountant,Finance Manager"}
        assert client.get("/api/pull-items/Purchase Invoice/sources", headers=h).json()["data"] == ["Purchase Order", "Purchase Receipt"]
        assert client.get("/api/pull-items/Journal Entry Voucher/sources", headers=h).json()["data"] == []
        found = client.post("/api/pull-items/candidates", headers=h, json={"target_doctype": "Purchase Receipt", "source_doctype": "Purchase Order", "party": supplier.name})
        assert found.status_code == 200 and found.json()["data"][0]["name"] == po.name and found.json()["data"][0]["open_quantity"] in ("7.0", "7", "7.000000")
        lines = client.post("/api/pull-items/lines", headers=h, json={"target_doctype": "Purchase Receipt", "source_doctype": "Purchase Order", "names": [po.name]})
        assert lines.status_code == 200 and lines.json()["data"]["lines"][0]["source_document"] == po.name
        wrong = client.post("/api/pull-items/lines", headers=h, json={"target_doctype": "Purchase Receipt", "source_doctype": "Sales Order", "names": [po.name]})
        assert wrong.status_code >= 400
    finally:
        velora.shutdown()
