from velora_governance.governance.services.governance_operations_dashboard import build_governance_operations_dashboard
from velora_governance.governance.services.governance_automation_monitor import build_automation_monitor
from velora_governance.governance.services.governance_configuration_center import validate_governance_configuration
from velora_governance.governance.services.governance_release_qualification import evaluate_governance_release_qualification, REQUIRED_GATES


def test_operations_dashboard_aggregates_and_attention_queue():
    result = build_governance_operations_dashboard(
        actions=[{"name": "A1", "status": "overdue", "owner": "Alice", "overdue": True},
                 {"name": "A2", "status": "open", "owner": "Bob"}],
        automation_runs=[{"name": "R1", "status": "failed", "retryable": True}],
        obligations=[{"status": "overdue", "overdue": True}],
        risks=[{"risk_level": "Critical"}], controls=[{"test_result": "ineffective"}],
        meetings=[{"upcoming": True}], notifications=[{"status": "failed"}])
    assert result["kpis"]["open_actions"] == 2
    assert result["kpis"]["overdue_actions"] == 1
    assert result["kpis"]["automation_failures"] == 1
    assert result["kpis"]["high_risks"] == 1
    assert result["kpis"]["control_failures"] == 1
    assert result["attention_count"] == 2
    assert result["open_actions_by_owner"] == {"Alice": 1, "Bob": 1}


def test_automation_monitor_identifies_retry_candidates_without_dispatch():
    result = build_automation_monitor([
        {"name": "F1", "status": "failed", "retryable": True, "attempts": 1, "idempotency_key": "k1"},
        {"name": "F2", "status": "failed", "retryable": True, "attempts": 3},
        {"name": "S1", "status": "dispatched"},
    ], max_retry_attempts=3)
    assert result["retry_candidate_count"] == 1
    assert result["retry_candidates"][0]["id"] == "F1"
    assert result["retry_execution_enabled"] is False
    assert result["success_count"] == 1


def test_configuration_center_rejects_invalid_and_approval_duplication():
    result = validate_governance_configuration(
        automation_rules=[{"name": "r1", "enabled": True, "trigger": "due", "action_type": "approval"}],
        templates=[{"name": "t1", "subject": "Reminder", "body": "Text"}],
        schedules=[{"name": "s1", "enabled": True, "cron": "0 8 * * *", "template": "missing"}],
        routing=[{"name": "route1", "enabled": True}])
    codes = {issue["code"] for issue in result["issues"]}
    assert result["valid"] is False
    assert "approval_must_use_native_workflow_engine" in codes
    assert "unknown_template_reference" in codes
    assert "missing_destination" in codes


def test_configuration_center_valid_configuration():
    result = validate_governance_configuration(
        automation_rules=[{"name": "r1", "trigger": "due", "action_type": "reminder"}],
        templates=[{"name": "t1", "subject": "Reminder", "body": "Body"}],
        schedules=[{"name": "s1", "cron": "0 8 * * *", "template": "t1"}],
        routing=[{"name": "route1", "destination": "Governance Inbox"}])
    assert result["valid"] is True
    assert result["error_count"] == 0


def test_release_qualification_requires_all_gates_and_evidence_refs():
    evidence = {gate: {"passed": True, "evidence_ref": f"TEST-{gate}"} for gate in REQUIRED_GATES}
    qualified = evaluate_governance_release_qualification(evidence)
    assert qualified["qualification_status"] == "qualified_for_release_review"
    assert qualified["production_qualified"] is False
    evidence["uat"] = {"passed": True}
    incomplete = evaluate_governance_release_qualification(evidence)
    assert incomplete["qualification_status"] == "not_qualified"
    assert "uat" in incomplete["blocking_gates"]
