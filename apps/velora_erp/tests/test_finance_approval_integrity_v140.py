"""The approval record stays honest (v2.84): with no workflow a document is simply approved; with one, the identity of the
approver is recorded by the system and cannot be typed in."""
from types import SimpleNamespace

import pytest

import velora
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.finance.source_documents import approval_required, ensure_approved, validate_approval_transition


def doc(**values):
    base = {"doctype": "Receipt", "approval_status": "Pending", "approved_by": None, "approved_on": None, "rejected_by": None, "rejected_on": None,
            "owner": "maker@velora.test", "docstatus": 0}
    base.update(values)
    return SimpleNamespace(**base)


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'ai.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate()
    yield
    velora.shutdown()


def test_with_no_workflow_a_pending_document_is_simply_approved(site):
    d = doc()
    assert not approval_required("Receipt")
    validate_approval_transition(d)
    assert d.approval_status == "Approved"
    ensure_approved(doc(approval_status="Pending"), required=True)             # nothing to wait for


def test_with_no_workflow_a_rejected_document_still_cannot_be_used(site):
    with pytest.raises(ValidationError, match="rejected"):
        ensure_approved(doc(approval_status="Rejected"), required=True)


def test_an_invalid_status_is_refused(site):
    with pytest.raises(ValidationError, match="Invalid approval status"):
        validate_approval_transition(doc(approval_status="Maybe"))


def test_with_a_workflow_a_new_document_starts_pending_and_identity_fields_are_system_controlled(site):
    from wf_helpers import install_approval
    install_approval("Receipt")
    assert approval_required("Receipt")
    with pytest.raises(ValidationError, match="starts as Pending"):
        validate_approval_transition(doc(approval_status="Approved"))
    with pytest.raises(ValidationError, match="system-controlled"):
        validate_approval_transition(doc(approved_by="someone@x.test"))
    with pytest.raises(ValidationError, match="waiting for approval"):
        ensure_approved(doc(), required=True)


def test_with_a_workflow_the_approver_and_time_are_stamped_by_the_system(site):
    from wf_helpers import install_approval
    install_approval("Receipt")
    d = doc(approval_status="Approved"); d._old = {"approval_status": "Pending", "approved_by": None, "approved_on": None, "rejected_by": None, "rejected_on": None}
    with session_as(Session("approver@velora.test", frozenset({"Finance Manager"}))):
        validate_approval_transition(d)
    assert d.approved_by == "approver@velora.test" and d.approved_on and d.rejected_by is None
    again = doc(approval_status="Approved", approved_by="forged@x.test"); again._old = {"approval_status": "Approved", "approved_by": "approver@velora.test", "approved_on": d.approved_on, "rejected_by": None, "rejected_on": None}
    with pytest.raises(ValidationError, match="system-controlled"):
        validate_approval_transition(again)
