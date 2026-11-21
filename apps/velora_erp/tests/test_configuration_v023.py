from datetime import date, datetime, timezone
from sqlalchemy import insert

import velora
from velora import db
from velora import settings_governance as sg
from velora_erp import configuration as cfg


def _site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'configuration.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate()

def _published(key, value):
    sg.ensure()
    with db.transaction() as conn:
        conn.execute(insert(sg.versions).values(
            id=f"test-{key}", setting=key, scope_type="legal_entity", scope_key="", version=1,
            value=value, effective_from=date.today(), change_request="test", actor="test", published_on=datetime.now(timezone.utc).replace(tzinfo=None),
        ))


def test_governed_overrides_only_apply_to_published_values(tmp_path):
    _site(tmp_path)
    _published("finance.allow_backdated_posting", False)
    result = cfg.apply_governed_settings("Finance Settings", {"allow_backdated_posting": True, "country_code": "NG"})
    assert result["allow_backdated_posting"] is False
    assert result["country_code"] == "NG"


def test_governed_overrides_do_not_cross_domain_or_change_unmapped_fields(tmp_path):
    _site(tmp_path)
    _published( "inventory.block_below_cost", False)
    result = cfg.apply_governed_settings("Inventory Settings", {
        "block_selling_below_cost": True, "strict_selling_price": True,
    })
    assert result["block_selling_below_cost"] is False
    assert result["strict_selling_price"] is True


def test_setup_readiness_reports_blocking_controls_and_warnings(monkeypatch):
    def get_list(doctype, **_kwargs):
        if doctype == "Finance Settings":
            return [{"name": "Primary", "base_currency": "NGN", "country_code": "NG"}]
        if doctype == "Inventory Settings":
            return [{"name": "Primary", "default_inventory_asset_account": "INV", "goods_received_not_invoiced_account": "GRNI",
                     "cost_of_goods_sold_account": "COGS", "stock_adjustment_gain_account": "GAIN", "stock_adjustment_loss_account": "LOSS"}]
        return []
    monkeypatch.setattr(cfg, "get_list", get_list)
    monkeypatch.setattr(cfg, "_count", lambda doctype, filters=None: {"Financial Year": 1, "Account": 10, "Financial Period": 12}.get(doctype, 0))
    result = cfg.setup_readiness()
    assert result["status"] == "ready"
    assert result["blocking_issues"] == 0
    assert result["warnings"] == 3
    assert result["total"] == 8


def test_company_setup_readiness_api_is_company_scoped_and_authenticated(tmp_path):
    _site(tmp_path)
    try:
        from fastapi.testclient import TestClient
        from velora.api import create_app
        client = TestClient(create_app(auto_init=False))
        admin = {"X-Velora-User": "setup-admin", "X-Velora-Roles": "System Manager"}
        response = client.get("/api/company/setup-readiness", headers=admin)
        assert response.status_code == 200
        body = response.json()["data"]
        assert body["status"] == "setup_required"
        assert body["blocking_issues"] >= 1
        assert {row["code"] for row in body["checks"]} >= {"FINANCE_SETTINGS", "INVENTORY_SETTINGS", "CHART_OF_ACCOUNTS"}
        employee = {"X-Velora-User": "setup-user", "X-Velora-Roles": "Employee"}
        # The checklist is read-only company configuration information; API access still requires authentication.
        assert client.get("/api/company/setup-readiness", headers=employee).status_code == 200
    finally:
        velora.shutdown()


def test_catalogue_seeding_is_idempotent_and_company_scoped(tmp_path):
    _site(tmp_path)
    try:
        created = cfg.seed_settings_catalogue()
        assert created == 18
        assert cfg.seed_settings_catalogue() == 0
        definitions = sg.list_definitions()
        assert len(definitions) == 18
        assert all(row["allowed_scopes"] == ["legal_entity"] for row in definitions)
    finally:
        velora.shutdown()
