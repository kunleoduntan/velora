import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_standard_business_documents_are_in_catalogue():
    catalogue = json.loads((ROOT / "velora_erp" / "docs" / "document-catalog.json").read_text())
    names = {entry["name"] for entry in catalogue["documents"]}
    assert {"Sales Invoice", "Purchase Invoice", "Sales Order", "Purchase Order"} <= names


def test_catalogue_distinguishes_implemented_masters_from_planned_transactions():
    catalogue = json.loads((ROOT / "velora_erp" / "docs" / "document-catalog.json").read_text())
    assert catalogue["status"] == "partially_implemented"
    assert {"Account", "Account Type", "Account Group", "Cost Centre"} <= set(catalogue["implemented_in_v0_2_0"])
    assert {"Financial Posting Batch", "Financial Posting Line", "Account Ledger Record"} <= set(catalogue["implemented_in_v0_3_0"])
    assert "Sales Invoice" in catalogue["implementation_note"]


def test_forbidden_legacy_core_names_not_in_catalogue():
    catalogue = json.loads((ROOT / "velora_erp" / "docs" / "document-catalog.json").read_text())
    names = {entry["name"] for entry in catalogue["documents"]}
    assert not {"GL Entry", "General Ledger Entry", "Journal Entry"} & names
