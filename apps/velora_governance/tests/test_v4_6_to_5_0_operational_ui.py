from velora_governance.governance.services.governance_dashboard_ui_contract import build_dashboard_view_model
from velora_governance.governance.services.governance_automation_history_ui import build_automation_history_view, preview_retry
from velora_governance.governance.services.governance_portal_workspace import build_portal_workspace
from velora_governance.governance.services.governance_configuration_bundle import export_configuration_bundle, validate_configuration_bundle, prepare_configuration_import
from velora_governance.governance.services.governance_v5_release_candidate import evaluate_v5_release_candidate, REQUIRED_RC_GATES


def test_dashboard_view_model_limits_attention_and_sections():
    result = build_dashboard_view_model({"kpis": {"open": 4}, "attention_items": list(range(5)), "private": "x"},
                                        visible_sections=["kpis", "attention_items"], max_attention_items=3)
    assert "private" not in result
    assert len(result["attention_items"]) == 3
    assert result["attention_truncated"] is True
    assert result["view_contract_version"] == "4.6.0"


def test_automation_history_filter_paginate_and_retry_fail_closed():
    rows = [{"name": f"R{i}", "status": "failed" if i < 4 else "completed", "action_type": "reminder"} for i in range(5)]
    result = build_automation_history_view(rows, page=2, page_size=2, filters={"status": "failed"})
    assert result["total"] == 4 and len(result["rows"]) == 2 and result["page"] == 2
    assert result["retry_execution_enabled"] is False
    preview = preview_retry({"name": "R1", "status": "failed", "retryable": True, "attempts": 1, "idempotency_key": "key"}, permission_checked=True, idempotency_verified=True)
    assert preview["eligible"] is True and preview["execution_enabled"] is False
    blocked = preview_retry({"name": "R1", "status": "failed", "retryable": True, "attempts": 3, "idempotency_key": "key"}, max_attempts=3)
    assert "attempt_limit_reached" in blocked["reasons"]
    assert "permission_check_required" in blocked["reasons"]


def test_portal_workspace_requires_permissions_and_scopes_rows():
    data = {"actions": [{"name": "A", "audience_id": "C1", "audience_type": "committee"},
                        {"name": "B", "audience_id": "C2", "audience_type": "committee"}]}
    blocked = build_portal_workspace(audience_type="committee", audience_id="C1", data=data)
    assert blocked["available"] is False
    result = build_portal_workspace(audience_type="committee", audience_id="C1", data=data,
                                    permitted_sections=["actions", "invalid"], permission_checked=True)
    assert result["sections"]["actions"] == [data["actions"][0]]
    assert "invalid" not in result["sections"]


def test_configuration_bundle_validation_and_import_prepare_are_safe():
    bundle = export_configuration_bundle({"automation_rules": [{"name": "r1"}], "templates": []})
    assert bundle["approval_workflow_included"] is False
    validation = validate_configuration_bundle(bundle)
    assert validation["valid"] is True and validation["import_enabled"] is False
    no_permission = prepare_configuration_import(bundle, validation_result=validation)
    assert no_permission["prepared"] is False
    prepared = prepare_configuration_import(bundle, validation_result=validation, permission_checked=True)
    assert prepared["prepared"] is True and prepared["apply_enabled"] is False
    invalid = validate_configuration_bundle({"bundle_name": "x", "configuration": {"rogue": []}})
    assert invalid["valid"] is False


def test_v5_release_candidate_requires_all_evidence_and_does_not_authorize_deploy():
    result = evaluate_v5_release_candidate()
    assert result["qualified"] is False and result["blocker_count"] == len(REQUIRED_RC_GATES)
    evidence = {gate: {"passed": True, "evidence_ref": f"E-{gate}"} for gate in REQUIRED_RC_GATES}
    qualified = evaluate_v5_release_candidate(evidence)
    assert qualified["qualified"] is True
    assert qualified["production_deployment_authorized"] is False
