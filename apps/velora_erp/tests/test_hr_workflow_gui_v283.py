"""Approval belongs to the GUI workflow engine, never to controller code (v2.83)."""
from datetime import date
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError, PermissionDenied
from velora.permissions import Session, session_as
from velora import workflows
from velora_erp.setup import after_install

SM = Session(user="admin1", roles=frozenset({"System Manager"}))
HRM = Session(user="hrm", roles=frozenset({"HR Manager"}))
STAFF = Session(user="staff@x.com", roles=frozenset({"Employee"}))


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'wf.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _leave(user_account=None):
    e = new_doc("Employee", employee_code="E1", employee_name="E1", employee_type="Permanent", date_of_joining=date(2020, 1, 1), user_account=user_account).insert(ignore_permissions=True)
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1).insert(ignore_permissions=True)
    a = new_doc("Leave Allocation", employee=e.name, leave_type=t.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
    return new_doc("Leave Application", employee=e.name, leave_type=t.name, leave_allocation=a.name, from_date=date(2026, 3, 2), to_date=date(2026, 3, 6), reason="Rest").insert(ignore_permissions=True)


def _remove(doctype):
    from sqlalchemy import delete
    with velora.db.transaction() as c:
        c.execute(delete(workflows.definition).where(workflows.definition.c.doctype == doctype))


def _leave_workflow():
    return {
        "name": "Leave Application Approval", "doctype": "Leave Application",
        "initial_state": "Draft", "state_field": "workflow_status",
        "states": [{"name": "Draft"}, {"name": "Pending Approval"},
                   {"name": "Approved", "is_final": True, "allows_submit": True}, {"name": "Rejected"}],
        "transitions": [
            {"action": "Submit for Approval", "from_state": "Draft", "to_state": "Pending Approval", "roles": [], "anyone": True},
            {"action": "Approve", "from_state": "Pending Approval", "to_state": "Approved", "roles": ["HR Manager", "System Manager"], "prevent_self_approval": True},
            {"action": "Reject", "from_state": "Pending Approval", "to_state": "Rejected", "roles": ["HR Manager", "System Manager"], "prevent_self_approval": True},
            {"action": "Reopen", "from_state": "Rejected", "to_state": "Draft", "roles": ["HR Manager", "System Manager"]},
        ],
    }


def _create_leave_workflow(enabled=False):
    with session_as(SM):
        return workflows.save_definition({**_leave_workflow(), "enabled": enabled})


def test_no_doc_type_specific_workflow_templates_are_installed(site):
    assert workflows.list_definitions() == []
    assert not any(t["installed"] for t in workflows.workflow_templates())   # sample starters may be offered, never installed
    _create_leave_workflow(enabled=False)
    assert not workflows.is_managed("Leave Application")


def test_only_system_manager_can_create_a_company_workflow(site):
    with session_as(HRM):
        with pytest.raises(PermissionDenied):
            workflows.save_definition({**_leave_workflow(), "enabled": True})


def test_status_cannot_be_typed_in_once_a_workflow_owns_it(site):
    la = _leave()
    _create_leave_workflow(enabled=True)
    with session_as(HRM):
        inst = workflows.start("Leave Application Approval", "Leave Application", la.name)
    doc = get_doc("Leave Application", la.name, ignore_permissions=True)
    doc.workflow_status = "Approved"
    with pytest.raises(ValidationError, match="approval workflow"):
        doc.save(ignore_permissions=True)
    doc = get_doc("Leave Application", la.name, ignore_permissions=True); doc.reason = "changed"; doc.save(ignore_permissions=True)   # other fields stay editable
    with session_as(HRM):
        workflows.act(inst["id"], "Submit for Approval")
    with session_as(SM):
        workflows.act(inst["id"], "Approve")
    assert get_doc("Leave Application", la.name, ignore_permissions=True).workflow_status == "Approved"
    assert get_doc("Leave Application", la.name, ignore_permissions=True).approved_by == "admin1"


def test_the_employee_concerned_cannot_approve_their_own_request(site):
    la = _leave(user_account="hrm")
    _create_leave_workflow(enabled=True)
    with session_as(SM):
        inst = workflows.start("Leave Application Approval", "Leave Application", la.name)
        workflows.act(inst["id"], "Submit for Approval")
    with session_as(HRM):
        with pytest.raises(PermissionDenied, match="separation"):
            workflows.act(inst["id"], "Approve")


def test_without_a_workflow_nothing_is_blocked_and_no_role_is_hardcoded(site):
    la = _leave("staff@x.com")               # the employee's own request: an employee reaches their own records only
    with session_as(STAFF):                  # no role names in code: authority is permissions + workflow only
        doc = get_doc("Leave Application", la.name, ignore_permissions=True); doc.workflow_status = "Pending Approval"; doc.save(ignore_permissions=True)
