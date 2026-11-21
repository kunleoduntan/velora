import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

ROOT = Path(__file__).parents[1] / "velora_erp" / "finance" / "doctype"

def test_sales_quotation_metadata_is_submittable_and_validity_controlled():
    meta = json.loads((ROOT / "sales_quotation" / "sales_quotation.json").read_text())
    fields = {field["fieldname"]: field for field in meta["fields"]}
    assert meta["is_submittable"] is True
    assert fields["valid_until"]["required"] is True
    assert fields["approval_status"]["options"] == ["Pending", "Approved", "Rejected"]
    assert fields["lines"]["options"] == "Sales Quotation Line"
    assert fields["total_amount"]["read_only"] is True

def test_sales_quotation_line_retains_inventory_pricing_controls():
    meta = json.loads((ROOT / "sales_quotation_line" / "sales_quotation_line.json").read_text())
    fields = {field["fieldname"]: field for field in meta["fields"]}
    for name in ("item_code", "quantity", "rate", "discount_percentage", "discount_amount", "price_basis", "cost_rate", "cost_source"):
        assert name in fields

def test_quotation_to_order_flow_is_active_and_partial():
    registry = (Path(__file__).parents[1] / "velora_erp" / "finance" / "document_flow" / "registry.py").read_text()
    assert 'DocumentFlow("Sales Quotation", "Sales Order", "Create Sales Order", "active", "quotation_order", "one_to_many"' in registry


def test_sales_quotation_register_report_is_registered():
    root = Path(__file__).parents[1] / "velora_erp" / "finance" / "report" / "sales_quotation_register"
    report = json.loads((root / "sales_quotation_register.json").read_text())
    assert report["ref_doctype"] == "Sales Quotation"
    assert {f["fieldname"] for f in report["filters"]} >= {"from_date", "to_date", "customer", "document_status"}
    assert (root / "sales_quotation_register.py").exists()

def test_sales_workspace_patch_registered():
    patches = (Path(__file__).parents[1] / "velora_erp" / "patches.txt").read_text()
    assert "velora_erp.patches.v0_17.extend_sales_workspace" in patches
