from types import SimpleNamespace
from unittest.mock import patch

import pytest
from velora.exceptions import ValidationError
from velora_admin.administration.doctype.request.request import Request


class FakeRequest:
    def set(self, field, value):
        setattr(self, field, value)


def _doc():
    doc = FakeRequest()
    doc.request_type = "IT Support"
    doc.requester = "EMP-001"
    doc.description = "Replace damaged laptop"
    doc.estimated_cost = 500
    doc.approval_matrix = "MAT-IT"
    doc.current_level = 0
    doc.status = "Draft"
    doc.approval_history = []
    doc.sla_due_datetime = None
    doc.sla_status = None
    return doc


def _matrix(levels=None, active=True):
    return SimpleNamespace(is_active=active, levels=levels or [
        SimpleNamespace(level_no=1, approver_type="Specific Role", approver_role="IT Manager", approver_user=None, min_amount=0, max_amount=0),
        SimpleNamespace(level_no=2, approver_type="Specific User", approver_role=None, approver_user="manager@example.com", min_amount=0, max_amount=1000),
    ])


def test_submission_builds_amount_filtered_approval_chain():
    doc = _doc()
    with patch("velora_admin.administration.doctype.request.request.get_doc", return_value=_matrix()):
        Request.before_submit(doc)
    assert doc.status == "Pending Approval"
    assert doc.current_level == 1
    assert [row["level_no"] for row in doc.approval_history] == [1, 2]
    assert doc.approval_history[0]["assigned_approver"] == "IT Manager"
    assert doc.sla_due_datetime


def test_submission_requires_matrix():
    doc = _doc()
    doc.approval_matrix = None
    with pytest.raises(ValidationError, match="Approval Matrix"):
        Request.before_submit(doc)


def test_submission_rejects_inactive_matrix():
    doc = _doc()
    with patch("velora_admin.administration.doctype.request.request.get_doc", return_value=_matrix(active=False)):
        with pytest.raises(ValidationError, match="inactive"):
            Request.before_submit(doc)


def test_negative_cost_is_rejected():
    doc = _doc()
    doc.estimated_cost = -1
    with pytest.raises(ValidationError, match="negative"):
        Request.validate(doc)


def test_dynamic_manager_is_resolved_to_login_during_submission():
    doc=_doc()
    matrix=_matrix(levels=[SimpleNamespace(level_no=1,approver_type="Requester's Manager",approver_role=None,approver_user=None,min_amount=0,max_amount=0)])
    requester=SimpleNamespace(name="EMP-001",user_account="requester@example.com",reports_to="EMP-002",department="DPT-1",disabled=False)
    manager=SimpleNamespace(name="EMP-002",user_account="manager@example.com",email=None,disabled=False)
    def get_doc(doctype,name):
        if doctype=="Approval Matrix": return matrix
        if doctype=="Employee" and name=="EMP-001": return requester
        if doctype=="Employee" and name=="EMP-002": return manager
        raise RuntimeError(f"Unexpected {doctype} {name}")
    with patch("velora_admin.administration.doctype.request.request.get_doc",side_effect=get_doc), patch("velora_admin.administration.doctype.request.request.get_list",return_value=[]), patch("velora_admin.administration.approval_service.get_doc",side_effect=get_doc):
        Request.before_submit(doc)
    assert doc.approval_history[0]["assigned_approver"]=="manager@example.com"


def test_dynamic_manager_self_approval_blocked():
    doc=_doc()
    matrix=_matrix(levels=[SimpleNamespace(level_no=1,approver_type="Requester's Manager",approver_role=None,approver_user=None,min_amount=0,max_amount=0)])
    requester=SimpleNamespace(name="EMP-001",user_account="requester@example.com",reports_to="EMP-001",department="DPT-1",disabled=False)
    with patch("velora_admin.administration.doctype.request.request.get_doc",side_effect=lambda dt,n: matrix if dt=="Approval Matrix" else requester), patch("velora_admin.administration.doctype.request.request.get_list",return_value=[]), patch("velora_admin.administration.approval_service.get_doc",side_effect=lambda dt,n: matrix if dt=="Approval Matrix" else requester):
        with pytest.raises(ValidationError,match="Self-approval"):
            Request.before_submit(doc)
