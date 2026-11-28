from datetime import date
from velora_governance.governance.services.governance_automation import evaluate_governance_items, build_automation_message

def test_reminder_and_escalation_candidates():
    result = evaluate_governance_items([
      {"id":"a","title":"Return","due_date":"2026-12-03","status":"Open","owner":"User"},
      {"id":"b","title":"Late","due_date":"2026-11-19","status":"Open"},
      {"id":"c","title":"Done","due_date":"2026-11-20","status":"Completed"}], today=date(2026,11,26))
    assert result["actions_generated"] == 2
    assert {a["action_type"] for a in result["actions"]} == {"Reminder", "Escalation"}

def test_custom_rules_and_message():
    r = evaluate_governance_items([{"id":"x","title":"Board meeting","due_date":"2026-11-28","status":"Open","owner":"A"}], today="2026-11-26", rules={"reminder_days_before":[2]})
    assert r["actions"][0]["action_type"] == "Reminder"
    assert "Board meeting" in build_automation_message(r["actions"][0])

def test_terminal_and_missing_due_date_skipped():
    r = evaluate_governance_items([{"id":"1","status":"Closed"},{"id":"2","status":"Open"}], today="2026-11-26")
    assert not r["actions"]
