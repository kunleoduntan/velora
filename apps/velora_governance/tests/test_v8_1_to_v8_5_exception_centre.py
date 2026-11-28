from datetime import date
from velora_governance.governance.services.governance_exception_centre import (
    classify_exception, route_exception, transition_exception,
    build_exception_centre, validate_escalation_policy,
)


def test_severity_thresholds():
    today = date(2026, 11, 26)
    assert classify_exception(due_date="2026-11-26", today=today)["severity"] == "Low"
    assert classify_exception(due_date="2026-11-19", today=today)["severity"] == "Medium"
    assert classify_exception(due_date="2026-11-12", today=today)["severity"] == "High"
    assert classify_exception(due_date="2026-10-27", today=today)["severity"] == "Critical"


def test_score_classification_overrides_due_date():
    assert classify_exception(risk_score=90)["severity"] == "Critical"
    assert classify_exception(risk_score=50)["severity"] == "Medium"


def test_routing_is_explicit():
    assert route_exception(severity="Critical", routing_config={"Critical": "Governance Administrator"})["route"] == "Governance Administrator"
    assert route_exception(severity="High")["routing_status"] == "unconfigured"


def test_transition_rules_and_evidence():
    assert transition_exception("Open", "Assigned")["valid"]
    assert not transition_exception("Open", "Closed")["valid"]
    assert not transition_exception("In Progress", "Resolved", evidence_required=True)["valid"]
    assert transition_exception("In Progress", "Resolved", evidence_required=True, evidence="Board minutes")["valid"]


def test_exception_centre_metrics_and_order():
    result = build_exception_centre([
        {"name": "E1", "title": "Minor", "due_date": "2026-11-24", "status": "Open"},
        {"name": "E2", "title": "Critical", "due_date": "2026-10-01", "status": "Escalated"},
        {"name": "E3", "title": "Closed", "due_date": "2026-10-01", "status": "Closed"},
    ], today=date(2026, 11, 26))
    assert result["total"] == 3
    assert result["active"] == 2
    assert result["overdue_active"] == 2
    assert result["critical_active"] == 1
    assert result["exceptions"][0]["name"] == "E2"


def test_escalation_policy_validation():
    valid = validate_escalation_policy([{"after_hours": 24, "route": "Governance Officer"}, {"after_hours": 48, "route": "Company Secretary"}])
    assert valid["valid"]
    assert not validate_escalation_policy([{"after_hours": 24, "route": "A"}, {"after_hours": 12, "route": "B"}])["valid"]
    assert not validate_escalation_policy([{"after_hours": 1}])["valid"]
