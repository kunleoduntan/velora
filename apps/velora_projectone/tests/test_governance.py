import pytest
from velora_projectone.projectone.services.governance import (
    evaluate_stage_gate, assess_change_impact, validate_document_revision,
    evaluate_closure_checklist, calculate_benefit_realisation,
)
from velora_projectone.projectone.services.workflow_lifecycle import validate_lifecycle_command
from velora_projectone.projectone.integrations.native_documents import CORE_DOCUMENTS


def test_stage_gate_reports_missing_evidence_and_requires_independent_approval():
    result = evaluate_stage_gate([{"id": "business_case", "description": "Approved business case"},
                                  {"id": "funding", "description": "Funding confirmed"}],
                                 {"business_case": "DOC-001"})
    assert result["passed"] is False
    assert result["missing_criteria"] == ["funding"]
    assert result["requires_independent_approval"] is True


def test_stage_gate_waiver_is_explicit_and_recorded():
    result = evaluate_stage_gate([{"id": "x", "description": "Criterion"}], {}, waiver_reason="Sponsor exception")
    assert result["passed"] and result["waived"]


def test_stage_gate_rejects_malformed_criteria():
    with pytest.raises(ValueError): evaluate_stage_gate([], {})


def test_change_impact_escalates_scope_and_schedule():
    result = assess_change_impact(schedule_days=20, cost_delta=500, scope_change=True,
                                  thresholds={"schedule_days": 10, "cost_delta": 1000})
    assert result["impact_level"] == "Major"
    assert result["requires_change_board"] is True
    assert result["requires_baseline_revision"] is True


def test_change_impact_is_minor_when_no_thresholds_breached():
    assert assess_change_impact(schedule_days=2, cost_delta=100)["impact_level"] == "Minor"


def test_document_revision_must_be_sequential_and_have_file_reference():
    assert validate_document_revision(current_version=2, proposed_version=3,
                                      file_reference="DOCS/PLAN-v3.pdf")["valid"]
    with pytest.raises(ValueError): validate_document_revision(current_version=2, proposed_version=4, file_reference="x")
    with pytest.raises(ValueError): validate_document_revision(current_version=2, proposed_version=3, file_reference=" ")


def test_closure_readiness_requires_all_controls_lessons_and_benefit_owner():
    checklist = {"deliverables_accepted": True, "financial_reconciled": True,
                 "commitments_cleared": True, "assets_handed_over": False}
    result = evaluate_closure_checklist(checklist)
    assert not result["ready_for_approval"]
    assert result["incomplete_controls"] == ["assets_handed_over"]
    ready = evaluate_closure_checklist({k: True for k in checklist}, lessons_learned="Captured", benefits_owner="U-8")
    assert ready["ready_for_approval"]


def test_benefit_realisation_calculation_and_zero_denominator():
    result = calculate_benefit_realisation(baseline_value=10, target_value=30, actual_value=20)
    assert result["realisation_percent"] == 50
    assert result["remaining_to_target"] == 10
    assert calculate_benefit_realisation(baseline_value=5, target_value=5, actual_value=5)["realisation_percent"] == 100


def test_governance_doctypes_are_allowlisted_and_workflow_is_maker_checker():
    for name in ("Project Stage Gate", "Project Benefit", "Project Decision Log", "Project Charter", "Project Business Case", "Project Document Register", "Project Closure"):
        assert name in CORE_DOCUMENTS
    doc = {"approval_status": "Pending Approval", "owner": "U-1"}
    with pytest.raises(PermissionError):
        validate_lifecycle_command("Project Charter", "approve", doc, "U-1", {"note": "reviewed"})
    assert validate_lifecycle_command("Project Charter", "approve", doc, "U-2", {"note": "reviewed"})["validated"]
