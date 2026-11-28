from velora_governance.governance.services.governance_exception_configuration import validate_exception_configuration, classify_with_configuration, validate_bulk_assignment


def test_exception_configuration_validates_increasing_thresholds():
    assert validate_exception_configuration({})["valid"]
    bad=validate_exception_configuration({"medium_days":4,"low_days":5})
    assert not bad["valid"] and "overdue_thresholds_must_increase" in bad["errors"]


def test_score_thresholds_validate_bounds_and_order():
    assert not validate_exception_configuration({"critical_score":101})["valid"]
    assert not validate_exception_configuration({"high_score":30,"medium_score":40})["valid"]


def test_custom_severity_rules_are_applied():
    cfg={"medium_days":3,"high_days":6,"critical_days":10,"medium_score":20,"high_score":50,"critical_score":80}
    result=classify_with_configuration(due_date="2026-11-15",today="2026-11-26",configuration=cfg)
    assert result["severity"]=="Critical" and result["overdue_days"]==11
    score=classify_with_configuration(risk_score=52,configuration=cfg)
    assert score["severity"]=="High"


def test_custom_route_resolution_from_config():
    from velora_governance.governance.services.governance_exception_persistence import normalize_exception_payload
    cfg={"critical_days":30,"routes":{"Critical":"Executive Governance"}}
    payload={"source_doctype":"Board Action","source_name":"BA-1","title":"Action overdue","due_date":"2020-01-01"}
    result=normalize_exception_payload(payload,configuration=cfg)
    assert result["valid"]
    assert result["normalized"]["route"]=="Executive Governance"


def test_bulk_assignment_validation_deduplicates_and_limits():
    result=validate_bulk_assignment(["GE-1","GE-1","GE-2"],"user@example.com")
    assert result["valid"] and result["names"]==["GE-1","GE-2"]
    assert validate_bulk_assignment([],"user")["reason"]=="exceptions_required"
    assert validate_bulk_assignment([f"GE-{i}" for i in range(201)],"user")["reason"]=="bulk_limit_exceeded"
