"""A Waybill can be prepared from a Delivery Note, a Sales Order or a Sales Invoice, in one or more consignments."""
from datetime import date
from decimal import Decimal
import pytest
from velora import get_list, new_doc
from velora.permissions import session_as
from test_document_flow import MAKER
from test_inventory_v012 import setup_inventory, approve_and_submit
from test_sales_review_v276 import _stock_in
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.document_flow.registry import get_document_flows

D = lambda v: Decimal(str(v or 0))


def test_waybill_from_order_and_partial_consignments_and_flow_catalogue(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
    supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
    rev = get_list("Account", filters={"account_code": "4000"}, fields=["name"], limit=1)[0]["name"]
    with session_as(MAKER):
        _stock_in(item, warehouse, supplier, qty=10, rate=120)
        so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                     lines=[{"item_code": item.name, "description": "x", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": rev}]).insert(ignore_permissions=True)
        so.submit(ignore_permissions=True)
        assert "Waybill" in [f["target_doctype"] for f in get_document_flows("Sales Order")]
        assert "Waybill" in [f["target_doctype"] for f in get_document_flows("Sales Invoice")]
        w1 = create_document_from("Sales Order", so.name, "Waybill", {"transporter": "Velora Logistics", "quantities": {so.lines[0].name: 1}})
        assert not w1.delivery_note and w1.source_document == so.name and D(w1.lines[0].quantity) == 1
        w1.submit(ignore_permissions=True)
        w2 = create_document_from("Sales Order", so.name, "Waybill")
        assert D(w2.lines[0].quantity) == 3                      # only what is left to ship
        with pytest.raises(Exception, match="remaining"):
            create_document_from("Sales Order", so.name, "Waybill", {"quantities": {so.lines[0].name: 5}})
        # a waybill with no delivery note cannot be billed as if it had one
        w2.submit(ignore_permissions=True)
        with pytest.raises(Exception, match="no Delivery Note"):
            create_document_from("Waybill", w2.name, "Sales Invoice")


def test_every_document_prints_with_the_standard_page_and_in_batches(tmp_path):
    from velora import printing
    from velora.exceptions import ValidationError
    item, warehouse, *_ = setup_inventory(tmp_path)
    customer = get_list("Customer", fields=["name"], limit=1)[0]["name"]
    supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
    rev = get_list("Account", filters={"account_code": "4000"}, fields=["name"], limit=1)[0]["name"]
    with session_as(MAKER):
        _stock_in(item, warehouse, supplier, qty=10, rate=120)
        so = new_doc("Sales Order", document_date=date.today(), party=customer, currency="NGN", exchange_rate=1,
                     lines=[{"item_code": item.name, "description": "Widgets <b>x</b>", "quantity": 4, "uom": "Each", "rate": 200, "revenue_account": rev}]).insert(ignore_permissions=True)
        so.submit(ignore_permissions=True)
        w1 = create_document_from("Sales Order", so.name, "Waybill", {"quantities": {so.lines[0].name: 1}}); w1.submit(ignore_permissions=True)
        w2 = create_document_from("Sales Order", so.name, "Waybill"); w2.submit(ignore_permissions=True)
        ids = [c["id"] for c in printing.choices_for("Waybill")]
        assert ids == ["standard"]                                    # nothing designed yet, yet printing still works
        one = printing.render("standard", "Waybill", w1.name)
        assert w1.name in one and "Lines" in one
        many = printing.render_many("standard", "Waybill", [w1.name, w2.name, "NOPE-1"])
        assert w1.name in many and w2.name in many and many.count("vp-doc'>") == 2 and "Not printed" in many
        with pytest.raises(ValidationError):
            printing.render_many("standard", "Waybill", [])
