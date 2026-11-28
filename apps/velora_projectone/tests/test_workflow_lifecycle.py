import pytest
from velora_projectone.projectone.services.workflow_lifecycle import validate_lifecycle_command


def test_project_approval_is_maker_checker():
    doc = {"status": "Draft", "owner": "U-1"}
    with pytest.raises(PermissionError):
        validate_lifecycle_command("Project", "approve", doc, "U-1", {"decision": "approve"})
    result = validate_lifecycle_command("Project", "approve", doc, "U-2", {"decision": "approve"})
    assert result["validated"] is True


def test_baseline_requires_submission_before_approval():
    doc = {"approval_status": "Draft", "owner": "U-1"}
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project Baseline", "approve", doc, "U-2", {"note": "reviewed"})
    assert validate_lifecycle_command("Project Baseline", "submit_for_approval", doc, "U-1")["validated"]
    doc["approval_status"] = "Pending Approval"
    assert validate_lifecycle_command("Project Baseline", "approve", doc, "U-2", {"note": "reviewed"})["validated"]


def test_task_completion_requires_evidence_and_valid_state():
    doc = {"status": "In Progress"}
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project Task", "complete", doc, "U-1")
    assert validate_lifecycle_command("Project Task", "complete", doc, "U-1", {"completion_note": "Done"})["validated"]
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project Task", "complete", {"status": "Open"}, "U-1", {"note": "x"})


def test_deliverable_acceptance_requires_evidence_and_maker_checker():
    doc = {"status": "In Progress", "owner": "U-1"}
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project Deliverable", "accept", doc, "U-2")
    with pytest.raises(PermissionError):
        validate_lifecycle_command("Project Deliverable", "accept", doc, "U-1", {"acceptance": "ok"})
    assert validate_lifecycle_command("Project Deliverable", "accept", doc, "U-2", {"acceptance": "ok"})["validated"]


def test_unknown_action_and_doctype_fail_closed():
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project", "force_status", {"status": "Draft"}, "U-1")
    with pytest.raises(ValueError):
        validate_lifecycle_command("User", "approve", {"status": "Draft"}, "U-1")


def test_risk_escalation_requires_evidence():
    doc = {"status": "Open"}
    with pytest.raises(ValueError):
        validate_lifecycle_command("Project Risk", "escalate", doc, "U-1")
    assert validate_lifecycle_command("Project Risk", "escalate", doc, "U-1", {"reason": "critical exposure"})["validated"]
