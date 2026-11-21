from types import SimpleNamespace

import pytest

from velora import db, jobs
from velora.controlplane.role_admin import RoleAdministration
from velora.exceptions import PermissionDenied
from velora.permissions import Session, get_session, session_as

ADMIN = SimpleNamespace(is_company_admin=True, email="admin@company.test", roles={"System Manager"})


def test_background_enqueue_requires_manager(site):
    with session_as(Session("sales@example.com", frozenset({"Sales User"}))):
        with pytest.raises(PermissionDenied):
            jobs.enqueue_job("tests.test_jobs._record", {"value": "blocked"})


def test_background_handler_runs_as_least_privilege_service_principal(site):
    observed = []

    def inspect_session(payload):
        s = get_session()
        observed.append((s.user, set(s.roles), dict(s.attributes)))
        return {"ok": True}

    jobs.register_handler("tests.test_security_completion_v039.inspect", inspect_session,
                          roles=("Background Reader",))
    with session_as(Session("manager@example.com", frozenset({"System Manager"}))):
        queued = jobs.enqueue_job("tests.test_security_completion_v039.inspect", {})
    result = jobs.process_due_jobs()
    assert result["completed"] == 1
    user, roles, attrs = observed[0]
    assert user == "service:tests.test_security_completion_v039.inspect"
    assert roles == {"Background Reader"}
    assert attrs["service_account"] is True
    assert attrs["created_by"] == "manager@example.com"
    assert attrs["job_id"] == queued["id"]
    # The caller/worker context is restored after the handler returns.
    assert get_session().user == "Administrator"


def test_summary_report_uses_row_level_read_policy(site):
    from velora.document import new_doc
    from velora.permissions import Session, session_as
    from velora.reporting.definition import ReportDef
    from velora.reporting.summary import run_summary

    svc = RoleAdministration(db.get_engine())
    svc.create_role(ADMIN, "Scoped Summary")
    for operation in ("create", "read"):
        svc.set_permission(ADMIN, "Scoped Summary", "Customer", operation, True)
    svc.set_row_policy(ADMIN, "Scoped Summary", "Customer", "create", [
        {"field": "owner", "operator": "equals_user"}])
    svc.set_row_policy(ADMIN, "Scoped Summary", "Customer", "read", [
        {"field": "owner", "operator": "equals_user"}])

    with session_as(Session("alice@example.com", frozenset({"Scoped Summary"}))):
        new_doc("Customer", customer_name="Alice", credit_limit=100).insert()
    with session_as(Session("bob@example.com", frozenset({"Scoped Summary"}))):
        new_doc("Customer", customer_name="Bob", credit_limit=900).insert()

    definition = ReportDef.from_dict({
        "name": "Customer Credit Summary", "type": "summary", "ref_doctype": "Customer",
        "group_by": ["status"], "measures": [{"fn": "sum", "field": "credit_limit", "label": "Credit"}],
    })
    with session_as(Session("alice@example.com", frozenset({"Scoped Summary"}))):
        result = run_summary(definition, {}).build()
    assert sum(float(row.values.get("m_0") or 0) for row in result.rows if row.type == "data") == 100.0
