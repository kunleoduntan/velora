from datetime import date, timedelta

import pytest

from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora import settings_governance as sg


def _definition(name="finance.base_currency", **overrides):
    data = {
        "name": name, "title": "Base Currency", "description": "Legal entity base currency",
        "domain": "finance", "value_type": "string", "allowed_scopes": ["legal_entity"],
        "fallback_scopes": [], "required": True, "risk": "critical",
    }
    data.update(overrides)
    return data


def test_setting_requires_reason_and_scope(site):
    sg.register_definition(_definition())
    with pytest.raises(ValidationError, match="business reason"):
        sg.create_change({"setting":"finance.base_currency", "scope_type":"legal_entity", "value":"NGN", "reason":""})
    with pytest.raises(ValidationError, match="not permitted"):
        sg.create_change({"setting":"finance.base_currency", "scope_type":"branch", "scope_key":"LAG", "value":"NGN", "reason":"Initial setup"})


def test_maker_checker_and_effective_dated_immutable_versions(site):
    sg.register_definition(_definition())
    effective = date.today() + timedelta(days=1)
    with session_as(Session("maker@example.com", frozenset({"System Manager"}))):
        change = sg.create_change({"setting":"finance.base_currency", "scope_type":"legal_entity",
            "value":"NGN", "reason":"Approved entity setup", "effective_from":effective.isoformat()})
        sg.transition_change(change["name"], "submit")
    with session_as(Session("checker@example.com", frozenset({"System Manager"}))):
        sg.transition_change(change["name"], "approve")
        assert sg.get_change(change["name"])["status"] == "pending_approval"
    with session_as(Session("second-checker@example.com", frozenset({"System Manager"}))):
        sg.transition_change(change["name"], "approve")
        sg.transition_change(change["name"], "publish")
        with pytest.raises(ValidationError, match="Required setting"):
            sg.get_effective("finance.base_currency", on_date=(effective-timedelta(days=1)).isoformat())
        current = sg.get_effective("finance.base_currency", on_date=effective.isoformat())
        assert current["value"] == "NGN"
        assert current["version"] == 1
        with pytest.raises(ValidationError):
            sg.transition_change(change["name"], "publish")
        history = sg.versions_for("finance.base_currency", "legal_entity", "")
        assert len(history) == 1
        assert history[0]["value"] == "NGN"
        published_audit=next(x for x in sg.audit_history("finance.base_currency") if x["event"]=="publish")
        assert published_audit["details"]["new_value"] == "NGN"
        assert published_audit["details"]["previous_value"] is None


def test_explicit_fallback_and_secret_reference_only(site):
    sg.register_definition(_definition("sales.default_warehouse", value_type="string",
        allowed_scopes=["branch", "legal_entity"], fallback_scopes=["legal_entity"], required=False,
        risk="normal", default_value="MAIN"))
    sg.register_definition(_definition("integration.api_key", value_type="secret_ref",
        allowed_scopes=["module"], required=False, risk="high", secret=True))
    with pytest.raises(ValidationError, match="secret://"):
        sg.create_change({"setting":"integration.api_key", "scope_type":"module", "scope_key":"payments",
            "value":"plain-secret", "reason":"Configure integration"})
    with session_as(Session("maker@example.com", frozenset({"System Manager"}))):
        change=sg.create_change({"setting":"integration.api_key", "scope_type":"module", "scope_key":"payments",
            "value":"secret://payments/provider-key", "reason":"Configure integration"})
        assert change["value"] == "secret://payments/provider-key"
        assert sg.get_effective("sales.default_warehouse", "branch", "LAG")["value"] == "MAIN"


def test_high_risk_cannot_be_backdated_and_types_are_enforced(site):
    sg.register_definition(_definition("finance.posting_lock", value_type="boolean", risk="high", required=False))
    with pytest.raises(ValidationError, match="cannot be backdated"):
        sg.create_change({"setting":"finance.posting_lock", "scope_type":"legal_entity", "value":True,
            "reason":"Retroactive lock", "effective_from":"2000-01-01"})
    with pytest.raises(ValidationError, match="true or false"):
        sg.create_change({"setting":"finance.posting_lock", "scope_type":"legal_entity", "value":"yes",
            "reason":"Enable posting lock"})


def test_non_admin_cannot_govern_settings(site):
    with session_as(Session("user@example.com", frozenset({"Employee"}))):
        with pytest.raises(PermissionDenied):
            sg.list_definitions()


def test_configuration_package_import_is_checksum_verified_and_staged(site):
    sg.register_definition(_definition("sales.default_price_list", value_type="string", required=False,
        risk="normal", default_value="RETAIL"))
    with session_as(Session("maker@example.com", frozenset({"System Manager"}))):
        change=sg.create_change({"setting":"sales.default_price_list", "scope_type":"legal_entity",
            "value":"WHOLESALE", "reason":"Approved commercial setup"})
        sg.transition_change(change["name"], "submit")
    with session_as(Session("checker@example.com", frozenset({"System Manager"}))):
        sg.transition_change(change["name"], "approve")
        sg.transition_change(change["name"], "publish")
        package=sg.export_package(["sales.default_price_list"])
    with session_as(Session("importer@example.com", frozenset({"System Manager"}))):
        altered={"package":package["package"],"sha256":"0"*64}
        with pytest.raises(ValidationError, match="checksum mismatch"):
            sg.import_package(altered)
        imported=sg.import_package(package)
        assert imported["verified"] is True
        assert imported["staged_count"] == 1
        assert imported["change_requests"][0]["status"] == "draft"
        assert sg.get_effective("sales.default_price_list")["value"] == "WHOLESALE"


def test_settings_governance_rest_endpoints_are_authorized(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    client=TestClient(create_app(auto_init=False))
    admin={"X-Velora-User":"settings-admin","X-Velora-Roles":"System Manager"}
    employee={"X-Velora-User":"employee","X-Velora-Roles":"Employee"}
    payload=_definition("operations.require_approval", value_type="boolean", required=False, risk="normal")
    response=client.post("/api/settings/catalogue", json=payload, headers=admin)
    assert response.status_code == 200
    assert client.get("/api/settings/catalogue", headers=employee).status_code == 403
    response=client.post("/api/settings/changes", json={"setting":"operations.require_approval",
        "scope_type":"legal_entity","value":True,"reason":"Enable independent review"}, headers=admin)
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "draft"
    assert client.get("/api/settings/operations.require_approval/effective", headers=employee).status_code == 403


def test_published_setting_contract_cannot_be_retyped(site):
    sg.register_definition(_definition("finance.base_currency", required=False, risk="high"))
    with session_as(Session("maker@example.com", frozenset({"System Manager"}))):
        change=sg.create_change({"setting":"finance.base_currency", "scope_type":"legal_entity",
            "value":"NGN", "reason":"Set entity currency"})
        sg.transition_change(change["name"], "submit")
    with session_as(Session("checker@example.com", frozenset({"System Manager"}))):
        sg.transition_change(change["name"], "approve")
        sg.transition_change(change["name"], "publish")
        with pytest.raises(ValidationError, match="cannot change its type"):
            sg.register_definition(_definition("finance.base_currency", value_type="integer", required=False, risk="normal"))
        with pytest.raises(ValidationError, match="risk classification downgraded"):
            sg.register_definition(_definition("finance.base_currency", required=False, risk="normal"))
