from velora_governance.governance.services.governance_task_runtime import run_task_automation
from velora_governance.governance.services.board_action_accountability import build_board_action_accountability
from velora_governance.governance.services.governance_control_intelligence import build_control_intelligence
from velora_governance.governance.services.compliance_intelligence import build_compliance_intelligence
from velora_governance.governance.services.executive_governance_command_centre import build_executive_governance_command_centre


def test_task_runtime_idempotency_and_planning_only():
    items=[{"id":"TASK-1","title":"File return","due_date":"2026-11-26","status":"Open","owner":"A"}]
    result=run_task_automation(items,today="2026-11-26")
    assert result["planned_actions"]
    assert result["dispatch_ready"] is False
    key=result["planned_actions"][0]["idempotency_key"]
    duplicate=run_task_automation(items,today="2026-11-26",existing_keys=[key])
    assert duplicate["suppressed_duplicates"] == 1
    assert not duplicate["planned_actions"]


def test_board_action_accountability_metrics():
    actions=[{"id":"A1","status":"Completed"},{"id":"A2","status":"Open","overdue":True,"owner":"X"},
             {"id":"A3","status":"Open","owner":None,"days_until_due":5}]
    result=build_board_action_accountability(actions)
    assert result["total"]==3 and result["open"]==2
    assert result["overdue"]==1 and result["unassigned"]==1
    assert result["completion_rate_percent"]==33.33


def test_control_intelligence_detects_failures_and_untested():
    controls=[{"id":"C1","title":"Approval control"},{"id":"C2","title":"Review control"}]
    risks=[{"id":"R1","control_id":"C1"}]
    tests=[{"control_id":"C1","result":"Fail"}]
    result=build_control_intelligence(controls,risks,tests)
    assert result["controls_ineffective"]==1
    assert result["controls_needing_testing"]==1
    assert result["risk_control_coverage"]==50.0


def test_compliance_intelligence_rollup():
    rows=[{"id":"O1","status":"Overdue","overdue":True,"authority":"Regulator A"},
          {"id":"O2","status":"Open","days_until_due":10,"authority":"Regulator B","owner":"X"},
          {"id":"O3","status":"Compliant"}]
    result=build_compliance_intelligence(rows)
    assert result["total"]==3 and result["overdue"]==1 and result["due_within_30_days"]==1
    assert result["compliance_rate_percent"]==33.33


def test_executive_command_centre_unifies_queues():
    result=build_executive_governance_command_centre(
      tasks=[{"id":"T1","status":"Overdue","overdue":True,"title":"Task overdue"}],
      actions=[{"id":"A1","status":"Open","overdue":True,"title":"Board action overdue","owner":"X"}],
      risks=[{"id":"R1","risk_level":"Critical","title":"Critical risk"}],
      obligations=[{"id":"O1","status":"Overdue","overdue":True,"title":"Regulatory return"}],
      controls=[{"id":"C1","title":"Control 1"}],control_tests=[])
    assert result["summary"]["priority_items"] >= 4
    assert result["summary"]["critical_risks"]==1
    assert result["summary"]["overdue_compliance"]==1
