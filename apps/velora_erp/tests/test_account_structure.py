import json
from pathlib import Path

from velora.meta.registry import Registry
from velora_erp.finance.accounting_rules import ROOT_TYPES, NORMAL_BALANCES

APP_ROOT = Path(__file__).resolve().parents[1]


def test_finance_account_structure_metadata_registers():
    registry = Registry()
    registry.load(["velora_erp"])
    expected = {"Account Group", "Account Type", "Account", "Cost Centre", "Accounting Dimension", "Dimension Value", "Financial Statement Row", "Account Statement Mapping", "Customer", "Customer Group", "Supplier", "Supplier Group", "Payment Terms"}
    assert expected <= set(registry._doctypes)


def test_account_hierarchy_and_statement_links_are_valid():
    registry = Registry()
    registry.load(["velora_erp"])
    assert registry._doctypes["Account"].get_field("account_group").options == "Account Group"
    assert registry._doctypes["Account"].get_field("account_type").options == "Account Type"
    assert registry._doctypes["Dimension Value"].get_field("dimension").options == "Accounting Dimension"
    assert registry._doctypes["Account Statement Mapping"].get_field("statement_row").options == "Financial Statement Row"


def test_account_type_supports_contra_balances():
    assert set(ROOT_TYPES) == {"Asset", "Liability", "Equity", "Income", "Expense"}
    assert set(NORMAL_BALANCES) == {"Debit", "Credit"}
    path = APP_ROOT / "velora_erp" / "finance" / "doctype" / "account_type" / "account_type.json"
    data = json.loads(path.read_text())
    fields = {f["fieldname"]: f for f in data["fields"]}
    assert fields["root_type"]["options"] == list(ROOT_TYPES)
    assert fields["normal_balance"]["options"] == list(NORMAL_BALANCES)


def test_account_doctype_uses_derived_financial_controls():
    path = APP_ROOT / "velora_erp" / "finance" / "doctype" / "account" / "account.json"
    data = json.loads(path.read_text())
    fields = {f["fieldname"]: f for f in data["fields"]}
    assert fields["account_group"]["required"] is True
    assert fields["account_type"]["options"] == "Account Type"
    assert fields["root_type"]["read_only"] is True
    assert fields["normal_balance"]["read_only"] is True
    assert fields["requires_party"]["read_only"] is True
    assert not fields["reconciliation_required"].get("read_only")      # v2.84: Allow Reconciliation is the user's setting, starting from the Account Type


def test_financial_statement_mapping_requires_explicit_basis():
    path = APP_ROOT / "velora_erp" / "finance" / "doctype" / "account_statement_mapping" / "account_statement_mapping.json"
    data = json.loads(path.read_text())
    fields = {f["fieldname"]: f for f in data["fields"]}
    assert fields["mapping_basis"]["required"] is True
    assert fields["statement_row"]["required"] is True


def test_upgrade_patch_seeds_account_types_for_existing_companies():
    from velora.upgrade.patches import discover
    patches = discover("velora_erp")
    assert "velora_erp.patches.v0_2.seed_account_types" in patches["post_model_sync"]
