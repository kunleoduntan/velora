from velora_governance.governance.services.governance_automation_execution import execute_governance_actions
from velora_governance.governance.services.governance_portal_views import build_portal_view
from velora_governance.governance.services.board_committee_portal import build_board_committee_portal
from velora_governance.governance.services.governance_analytics_trends import build_governance_trends
from velora_governance.governance.services.governance_platform_readiness import build_platform_readiness


def test_automation_execution_dry_run_and_idempotency():
    action = {"action_type": "reminder", "idempotency_key": "x1"}
    dry = execute_governance_actions([action], dispatchers={"reminder": lambda a: {"ok": 1}})
    assert dry["outcomes"][0]["status"] == "validated"
    calls = []
    live = execute_governance_actions([action, action], dispatchers={"reminder": lambda a: calls.append(a) or {"sent": True}}, dry_run=False)
    assert live["dispatched"] == 1 and len(calls) == 1
    duplicate = execute_governance_actions([action], existing_keys=["x1"], dry_run=False)
    assert duplicate["outcomes"][0]["status"] == "duplicate_suppressed"


def test_portal_views_configuration_is_not_permission_grant():
    view = build_portal_view("Company Secretary", role_config={"Company Secretary": {"sections": ["actions", "reports", "bad"]}})
    assert view["sections"] == ["actions", "reports"]
    assert "not an authorization" in view["warning"]


def test_board_portal_committee_filtering():
    portal = build_board_committee_portal(committee="Audit", meetings=[{"committee":"Audit"},{"committee":"Risk"}],
        agenda_items=[{"committee":"Audit"}], actions=[{"committee":"Risk"}], resolutions=[])
    assert portal["summary"]["meetings"] == 1
    assert portal["summary"]["actions"] == 0


def test_trend_aggregation_and_user_benchmark():
    result = build_governance_trends([{"date":"2026-01-01","value":2},{"date":"2026-01-15","value":3},{"date":"2026-02-02","value":4}], benchmarks={"target":5})
    assert [s["total"] for s in result["series"]] == [5,4]
    assert result["benchmarks"][0]["variance"] == -1
    assert result["benchmarks"][0]["source"] == "user_supplied"


def test_readiness_reports_missing_native_integrations():
    result = build_platform_readiness(integrations={"permissions":"ready"}, test_results={"passed":8,"failed":0})
    assert result["readiness"] == "not_ready"
    assert not result["production_qualified"]
    assert result["failed_checks"] > 0
