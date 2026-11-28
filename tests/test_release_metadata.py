"""Regression checks for transaction form and child-grid metadata defaults."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "apps" / "velora_erp" / "velora_erp"


def spec(doctype: str):
    matches = [json.loads(path.read_text()) for path in APP.rglob("*.json")
               if json.loads(path.read_text()).get("name") == doctype]
    assert matches, f"Missing DocType metadata: {doctype}"
    return matches[0]


def fields(doctype: str):
    return {field["fieldname"]: field for field in spec(doctype)["fields"]}


def test_sales_and_purchase_transaction_party_names_fetch_from_the_master():
    for doctype in ("Sales Invoice", "Sales Order", "Sales Quotation", "Delivery Note", "Sales Return"):
        assert fields(doctype)["customer_name"]["fetch_from"] == "party.customer_name"
    for doctype in ("Purchase Invoice", "Purchase Order", "Purchase Receipt", "Purchase Return"):
        assert fields(doctype)["supplier_name"]["fetch_from"] == "party.supplier_name"
    assert fields("Supplier Quotation")["supplier_name"]["fetch_from"] == "supplier.supplier_name"


def test_sales_and_purchase_item_tables_expose_compact_erp_style_columns():
    expected = {
        "Sales Invoice Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
        "Sales Order Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
        "Sales Quotation Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
        "Purchase Invoice Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
        "Purchase Order Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
        "Supplier Quotation Line": {"item_code", "item_name", "quantity", "rate", "amount", "warehouse"},
    }
    for doctype, columns in expected.items():
        selected = {name for name, field in fields(doctype).items() if field.get("in_list_view")}
        assert selected == columns, f"Unexpected default columns for {doctype}: {selected}"
        assert fields(doctype)["item_name"]["fetch_from"] == "item_code.item_name"


def test_every_inventory_item_child_table_can_fetch_its_item_name():
    for path in APP.rglob("*.json"):
        data = json.loads(path.read_text())
        if not data.get("istable"):
            continue
        item = next((field for field in data.get("fields", []) if field.get("fieldname") == "item_code"), None)
        if not item or item.get("fieldtype") != "Link" or item.get("options") != "Inventory Item":
            continue
        item_name = next((field for field in data.get("fields", []) if field.get("fieldname") == "item_name"), None)
        assert item_name and item_name.get("fetch_from") == "item_code.item_name", data.get("name")


def test_budget_grid_uses_a_summary_selection_not_all_twelve_month_columns():
    selected = {name for name, field in fields("Financial Budget Account").items() if field.get("in_list_view")}
    assert selected == {"account", "cost_centre", "total"}
