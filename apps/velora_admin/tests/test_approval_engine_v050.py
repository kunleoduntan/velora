from types import SimpleNamespace
from unittest.mock import patch

import pytest
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_admin.administration import approval_service as svc


def _doc():
    rows = [
        SimpleNamespace(level_no=1, approver_type="Specific Role", assigned_approver="IT Manager", status="Pending", action_on=None, comments=None),
        SimpleNamespace(level_no=2, approver_type="Specific User", assigned_approver="approver@example.com", status="Pending", action_on=None, comments=None),
    ]
    return SimpleNamespace(name="REQ-001", docstatus=1, status="Pending Approval", current_level=1,
                         approval_history=rows, save=lambda: None)


def test_role_approver_approves_and_activates_next_level():
    doc = _doc()
    with patch.object(svc, "get_doc", return_value=doc), session_as(Session("user1", frozenset({"IT Manager"}))):
        result = svc.approve("REQ-001", "Reviewed")
    assert result["status"] == "Pending Approval"
    assert result["next_level"] == 2
    assert doc.approval_history[0].status == "Approved"
    assert doc.current_level == 2
    assert doc.approval_history[1].status == "Pending"


def test_specific_user_approves_final_level():
    doc = _doc()
    doc.current_level = 2
    with patch.object(svc, "get_doc", return_value=doc), session_as(Session("approver@example.com", frozenset())):
        result = svc.approve("REQ-001")
    assert result["status"] == "Approved"
    assert doc.current_level == 0


def test_rejection_requires_comment():
    with pytest.raises(ValidationError, match="mandatory"):
        svc.reject("REQ-001", "")


def test_reject_marks_request_and_current_level():
    doc = _doc()
    with patch.object(svc, "get_doc", return_value=doc), session_as(Session("user1", frozenset({"IT Manager"}))):
        result = svc.reject("REQ-001", "Insufficient justification")
    assert result["status"] == "Rejected"
    assert doc.approval_history[0].status == "Rejected"
    assert doc.current_level == 0


def test_unassigned_user_cannot_approve():
    doc = _doc()
    with patch.object(svc, "get_doc", return_value=doc), session_as(Session("user2", frozenset({"Employee"}))):
        with pytest.raises(ValidationError, match="not assigned"):
            svc.approve("REQ-001")


def test_dynamic_manager_resolves_to_manager_login_and_blocks_self_approval():
    requester = SimpleNamespace(name="EMP-REQ", user_account="requester@example.com", reports_to="EMP-MGR", department="DPT-1", disabled=False)
    manager = SimpleNamespace(name="EMP-MGR", user_account="manager@example.com", disabled=False)
    doc = SimpleNamespace(requester="EMP-REQ", department="DPT-1")
    with patch.object(svc, "get_doc", side_effect=lambda doctype, name: requester if (doctype, name)==("Employee", "EMP-REQ") else manager):
        assert svc._resolve_dynamic_approver(doc, "Requester's Manager") == "manager@example.com"


def test_active_delegation_allows_delegate_to_approve():
    doc = _doc()
    delegation = {"delegator_user":"IT Manager", "delegate_user":"delegate", "start_date":None, "end_date":None, "doctype_scope":"Request"}
    with patch.object(svc, "get_doc", return_value=doc), patch.object(svc, "_active_delegations_for", return_value=[delegation]), session_as(Session("delegate", frozenset())):
        result = svc.approve("REQ-001", "Acting under delegation")
    assert result["status"] == "Pending Approval"
    assert doc.approval_history[0].comments == "Acting under delegation"


def test_dynamic_department_head_resolves_department_employee_login():
    requester = SimpleNamespace(name="EMP-REQ", user_account="requester@example.com", reports_to=None, department="DPT-1", disabled=False)
    head = SimpleNamespace(name="EMP-HOD", user_account="head@example.com", disabled=False)
    dept = SimpleNamespace(name="DPT-1", department_head="EMP-HOD")
    doc = SimpleNamespace(requester="EMP-REQ", department="DPT-1")
    def get_doc(doctype, name):
        return {("Employee", "EMP-REQ"): requester, ("Employee", "EMP-HOD"): head, ("Department", "DPT-1"): dept}[(doctype, name)]
    with patch.object(svc, "get_doc", side_effect=get_doc):
        assert svc._resolve_dynamic_approver(doc, "Department Head") == "head@example.com"
