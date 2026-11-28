import json
from pathlib import Path

from velora.meta.registry import Registry

APP_ROOT = Path(__file__).resolve().parents[1]


def test_finance_doctypes_register_without_legacy_names(monkeypatch):
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    names = set(registry._doctypes)
    assert {"Finance Settings", "Financial Year", "Financial Period", "Financial Posting Batch", "Financial Posting Line", "Account Ledger Record"} <= names
    assert "GL Entry" not in names
    assert "General Journal" not in names


def test_financial_period_links_to_financial_year():
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    period = registry._doctypes["Financial Period"]
    field = next(f for f in period.fields if f.fieldname == "financial_year")
    assert field.fieldtype == "Link"
    assert field.options == "Financial Year"


def test_finance_settings_has_one_central_grouped_configuration_document():
    path = APP_ROOT / "velora_erp" / "finance" / "doctype" / "finance_settings" / "finance_settings.json"
    data = json.loads(path.read_text())
    assert data["name"] == "Finance Settings"
    assert data["autoname"] == "field:settings_name"
    tabs = [f["label"] for f in data["fields"] if f["fieldtype"] == "Tab Break"]
    assert tabs == ["General", "Posting Controls", "Approvals", "Currency and Exchange Rates", "Tax Defaults", "Audit and Control", "Payroll and Employee Finance", "Investments"]


def test_install_hook_is_declared():
    import sys
    sys.path.insert(0, str(APP_ROOT))
    try:
        import velora_erp.hooks as hooks
        assert hooks.after_install == "velora_erp.setup.after_install"
    finally:
        sys.path.remove(str(APP_ROOT))


def test_posting_batch_and_ledger_metadata_enforce_separation():
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    batch = registry._doctypes["Financial Posting Batch"]
    ledger = registry._doctypes["Account Ledger Record"]
    assert batch.is_submittable is True
    assert batch.get_field("lines").options == "Financial Posting Line"
    assert ledger.get_field("posting_batch").options == "Financial Posting Batch"
    assert not any(p.create or p.write or p.delete for p in ledger.permissions)


def test_operational_sales_purchasing_and_logistics_documents_register():
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    names = set(registry._doctypes)
    assert {"Sales Order", "Sales Order Line", "Delivery Note", "Delivery Note Line", "Waybill", "Waybill Line", "Purchase Order", "Purchase Order Line", "Purchase Receipt", "Purchase Receipt Line"} <= names
