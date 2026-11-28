import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def meta(area, doctype):
    return json.loads((ROOT / f"apps/velora_erp/velora_erp/{area}/doctype/{doctype}/{doctype}.json").read_text())


def test_recruitment_uses_human_readable_document_series():
    assert meta("hr", "candidate")["autoname"] == "series:CAN-.####"
    assert meta("hr", "job_application")["autoname"] == "series:APP-.####"
    assert meta("hr", "interview")["autoname"] == "series:INT-.####"
    assert meta("hr", "job_posting")["autoname"] == "series:JOB-.####"


def test_ats_inbox_and_settings_are_configurable_and_secret_safe():
    inbox = meta("hr", "recruitment_inbox_notification")
    settings = meta("hr", "recruitment_settings")
    inbox_fields = {f["fieldname"] for f in inbox["fields"]}
    settings_fields = {f["fieldname"] for f in settings["fields"]}
    assert {"recipient", "event_type", "job_application", "interview", "notification_status"} <= inbox_fields
    assert {"pipeline_stages", "ai_enabled", "ai_provider", "ai_model", "ai_credential_reference", "ai_features"} <= settings_fields
    assert "api_key" not in settings_fields and "secret_key" not in settings_fields


def test_inventory_item_has_accounting_defaults():
    item = meta("finance", "inventory_item")
    fields = {f["fieldname"]: f for f in item["fields"]}
    assert {"expense_account", "income_account", "cost_of_sales_account", "default_cost_centre"} <= set(fields)
    assert fields["expense_account"]["options"] == "Account"


def test_finance_workspace_exposes_reports_and_recruitment_workspace_is_registered():
    source = (ROOT / "apps/velora_erp/velora_erp/setup.py").read_text()
    assert '"title": "Customer Ledger"' in source
    assert '"title": "Sales Margin Analysis"' in source
    assert "def ensure_recruitment_workspace" in source
    assert "ensure_recruitment_workspace()" in source


def test_link_field_supports_create_new_and_report_filter_grid_is_enabled():
    link = (ROOT / "frontend/src/components/LinkField.tsx").read_text()
    report = (ROOT / "frontend/src/components/ReportView.tsx").read_text()
    table = (ROOT / "frontend/src/components/TableField.tsx").read_text()
    assert "Create new ${doctype}" in link
    assert "report-filter-grid" in report
    assert "grid-toolbar-bottom" in table
