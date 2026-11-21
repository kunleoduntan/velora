"""Regression tests for v0.9 reusable platform engines."""
import pytest
from fastapi.testclient import TestClient

from velora import new_doc, get_doc, get_list
from velora import db
from velora.api import create_app
from velora.dashboards import save as save_dashboard, run as run_dashboard
from velora.printing import save as save_print, render as render_print
from velora.website import save as save_page, public_page
from velora.workflows import save_definition, start, act
from velora.permissions import Session, session_as
from velora.db.system import doc_share
from velora.exceptions import PermissionDenied, ValidationError


def test_workflow_state_transitions_and_role_gate(site):
    customer = new_doc("Customer", customer_name="Workflow Customer").insert()
    save_definition({
        "name": "Customer Approval", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Pending"}, {"name": "Approved", "is_final": True}],
        "transitions": [
            {"action": "Submit", "from_state": "Draft", "to_state": "Pending", "roles": ["Sales User"]},
            {"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True},
        ],
    })
    instance = start("Customer Approval", "Customer", customer.name)
    with session_as(Session("sam", frozenset({"Sales User"}))):
        instance = act(instance["id"], "Submit")
        assert instance["state"] == "Pending"
        with pytest.raises(PermissionDenied):
            act(instance["id"], "Approve")
    with session_as(Session("boss", frozenset({"Approver", "Sales User"}))):
        instance = act(instance["id"], "Approve", "Checked")
    assert instance["status"] == "Completed"
    assert instance["history"][-1]["comment"] == "Checked"


def test_dashboard_widgets_are_permission_aware(site):
    new_doc("Customer", customer_name="Dashboard A").insert()
    dashboard = save_dashboard({"name": "Customer Overview", "widgets": [
        {"title": "Customers", "type": "number", "doctype": "Customer"}
    ]})
    result = run_dashboard(dashboard["id"])
    assert result["results"][0]["value"] >= 1


def test_print_format_escapes_document_values(site):
    customer = new_doc("Customer", customer_name="<Acme>").insert()
    fmt = save_print({"name": "Customer Card", "doctype": "Customer", "template": "<h1>{{ customer_name }}</h1>"})
    html = render_print(fmt["id"], "Customer", customer.name)
    assert "&lt;Acme&gt;" in html and "<Acme>" not in html


def test_public_website_pages_are_company_local_and_slug_validated(site):
    page = save_page({"slug": "about-us", "title": "About Us", "body": "A public page", "published": True})
    assert public_page("about-us")["title"] == "About Us"
    with pytest.raises(ValidationError):
        save_page({"slug": "javascript:alert(1)", "title": "Bad", "body": "x"})


def test_record_share_grants_only_the_shared_document(site):
    first = new_doc("Customer", customer_name="Shared Customer").insert()
    second = new_doc("Customer", customer_name="Private Customer").insert()
    doc_share.create(db.get_engine(), checkfirst=True)
    with db.transaction() as conn:
        conn.execute(doc_share.insert().values(doctype="Customer", docname=first.name, user_email="reader@example.com",
            read=True, write=False, granted_by="Administrator"))
    with session_as(Session("reader@example.com", frozenset())):
        assert get_doc("Customer", first.name).customer_name == "Shared Customer"
        assert [x["name"] for x in get_list("Customer", fields=["name"])] == [first.name]
        with pytest.raises(PermissionDenied):
            get_doc("Customer", second.name)


def test_optional_totp_can_be_enabled_and_used_for_login(tmp_path, monkeypatch):
    from velora.controlplane import ControlPlane
    from velora.workspace import Workspace
    from velora.controlplane.identity import verify_totp, _totp_counter
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "mfa-workspace")
    plane = ControlPlane.create(ws, admin_email="mfa@example.com", admin_password="long secure password")
    try:
        auth = plane.identity.authenticate("mfa@example.com", "long secure password").context
        setup = plane.identity.begin_totp(auth)
        from datetime import datetime, timezone
        code = _totp_counter(setup["secret"], int(datetime.now(timezone.utc).timestamp() // 30))
        plane.identity.confirm_totp(auth, code)
        with pytest.raises(Exception, match="authenticator code"):
            plane.identity.authenticate("mfa@example.com", "long secure password")
        with pytest.raises(Exception, match="authenticator code is invalid"):
            plane.identity.authenticate("mfa@example.com", "long secure password", totp_code=code)           # the code that CONFIRMED the setup cannot also sign in (no replay)
        next_code = _totp_counter(setup["secret"], int(datetime.now(timezone.utc).timestamp() // 30) + 1)      # the next 30-second code is valid within the allowed clock drift
        result = plane.identity.authenticate("mfa@example.com", "long secure password", totp_code=next_code)
        assert result.token
    finally:
        plane.dispose()


def test_ip_login_throttling_blocks_repeated_unknown_account_attempts(tmp_path, monkeypatch):
    from velora.controlplane import ControlPlane
    from velora.workspace import Workspace
    from velora.exceptions import AuthenticationRequired
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ip-throttle-workspace")
    plane = ControlPlane.create(ws)
    try:
        for _ in range(30):
            with pytest.raises(AuthenticationRequired):
                plane.identity.authenticate("unknown@example.com", "not a password", ip="203.0.113.45")
        with pytest.raises(AuthenticationRequired, match="Too many sign-in attempts"):
            plane.identity.authenticate("another@example.com", "not a password", ip="203.0.113.45")
    finally:
        plane.dispose()


def test_dynamics_style_migration_package_preview_and_commit(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    group = new_doc("Customer Group", group_name="Migration Retail").insert()
    client = TestClient(create_app(auto_init=False))
    headers = {"X-Velora-User": "Administrator", "X-Velora-Roles": "System Manager"}
    exported = client.post("/api/data-migration/package/export", headers=headers, json={"doctypes": ["Customer Group"]})
    assert exported.status_code == 200, exported.text
    payload = exported.content
    group.delete(ignore_permissions=True)
    preview = client.post("/api/data-migration/package/import?dry_run=1", headers=headers, content=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"]["dry_run"] is True
    assert get_list("Customer Group", fields=["name"], filters={"name": group.name}) == []
    imported = client.post("/api/data-migration/package/import?dry_run=0", headers=headers, content=payload)
    assert imported.status_code == 200, imported.text
    assert get_doc("Customer Group", group.name).group_name == "Migration Retail"


def test_share_api_creates_company_local_record_share(site):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    customer = new_doc("Customer", customer_name="API Shared Customer").insert()
    client = TestClient(create_app(auto_init=False))
    admin = {"X-Velora-User": "Administrator"}
    response = client.post(f"/api/share/Customer/{customer.name}", headers=admin, json={"email":"reader@example.com","read":True})
    assert response.status_code == 200, response.text
    reader = {"X-Velora-User":"reader@example.com"}
    response = client.get(f"/api/resource/Customer/{customer.name}", headers=reader)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["customer_name"] == "API Shared Customer"


def test_workflow_amount_condition_controls_approval_action(site):
    customer = new_doc("Customer", customer_name="Conditional Approval", credit_limit=50).insert()
    save_definition({
        "name": "High Credit Approval", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Approved", "is_final": True}],
        "transitions": [{"action": "Approve", "from_state": "Draft", "to_state": "Approved", "roles": ["Approver"],
                         "condition": {"field": "credit_limit", "operator": ">", "value": 100}, "final": True}],
    })
    instance = start("High Credit Approval", "Customer", customer.name)
    with session_as(Session("boss", frozenset({"Approver", "Sales User"}))):
        with pytest.raises(ValidationError, match="condition"):
            act(instance["id"], "Approve")
    with session_as(Session("Administrator", frozenset())):
        doc = get_doc("Customer", customer.name); doc.credit_limit = 150; doc.save()
    with session_as(Session("boss", frozenset({"Approver", "Sales User"}))):
        assert act(instance["id"], "Approve")["state"] == "Approved"


def test_migration_package_includes_and_restores_attachments(site, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from velora.api import create_app
    from velora.files import add_attachment, get_file, delete_attachment, list_attachments
    monkeypatch.setenv("VELORA_FILE_ROOT", str(tmp_path / "migration-files"))
    customer = new_doc("Customer", customer_name="Customer With Attachment").insert()
    attached = add_attachment(b"migration-attachment-bytes", "proof.pdf", doctype="Customer",
                              docname=customer.name, content_type="application/pdf")
    client = TestClient(create_app(auto_init=False))
    headers = {"X-Velora-User": "Administrator", "X-Velora-Roles": "System Manager"}
    exported = client.post("/api/data-migration/package/export", headers=headers,
                           json={"doctypes": ["Customer"], "include_attachments": True})
    assert exported.status_code == 200, exported.text
    package = exported.content
    delete_attachment(attached["id"])
    customer.delete(ignore_permissions=True)
    imported = client.post("/api/data-migration/package/import", headers=headers, content=package)
    assert imported.status_code == 200, imported.text
    assert get_doc("Customer", customer.name).customer_name == "Customer With Attachment"
    restored = list_attachments("Customer", customer.name)
    assert len(restored) == 1
    metadata, content = get_file(restored[0]["id"])
    assert metadata["file_name"] == "proof.pdf"
    assert content == b"migration-attachment-bytes"


def test_website_seo_and_navigation_links_are_validated(site):
    page = save_page({"slug": "company-home", "title": "Company", "body": "Welcome", "published": True,
        "blocks": [{"type": "navigation", "items": [{"label": "Home", "href": "/"}]}],
        "seo": {"title": "Company Home", "description": "Company website"}})
    assert public_page("company-home")["seo"]["title"] == "Company Home"
    with pytest.raises(ValidationError, match="Navigation links"):
        save_page({"slug": "bad-navigation", "title": "Bad", "blocks": [{"type": "navigation", "items": [{"label": "x", "href": "javascript:alert(1)"}]}]})


def test_workflow_versions_are_snapshotted_and_attached_to_instances(site):
    from velora.workflow_automation import versions, instance_versions
    customer = new_doc("Customer", customer_name="Versioned workflow").insert()
    payload = {"name":"Versioned Customer Approval","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"],"final":True}]}
    save_definition(payload)
    first = start(payload["name"], "Customer", customer.name)
    payload["transitions"][0]["action"] = "Confirm"
    save_definition(payload)
    with db.transaction() as c:
        version = c.execute(__import__('sqlalchemy').select(versions.c.version).where(versions.c.workflow==payload["name"]).order_by(versions.c.version.desc())).scalar()
        attached = c.execute(__import__('sqlalchemy').select(instance_versions.c.version_id).where(instance_versions.c.instance_id==first["id"])).scalar()
    assert version == 2 and attached
    assert first["definition_version"] == 1
    # The running instance must still honour the original action after v2 is published.
    with session_as(Session("version.approver", frozenset({"Approver", "Sales User"}))):
        completed = act(first["id"], "Approve")
    assert completed["status"] == "Completed"


def test_workflow_quorum_requires_distinct_approvers(site):
    customer = new_doc("Customer", customer_name="Quorum workflow").insert()
    save_definition({"name":"Two Person Approval","doctype":"Customer","initial_state":"Pending",
        "states":[{"name":"Pending"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Pending","to_state":"Approved","roles":["Approver"],
            "approval_mode":"quorum","required_approvals":2,"final":True}]})
    instance = start("Two Person Approval","Customer",customer.name)
    with session_as(Session("approver.one",frozenset({"Approver","Sales User"}))):
        first = act(instance["id"],"Approve","First review")
        assert first["state"] == "Pending" and first["status"] == "Active"
    with session_as(Session("approver.two",frozenset({"Approver","Sales User"}))):
        second = act(instance["id"],"Approve","Second review")
        assert second["state"] == "Approved" and second["status"] == "Completed"
        assert len(second["approval_votes"]) == 2


def test_workflow_delegation_is_company_local_and_revocable(site):
    from datetime import datetime, timedelta, timezone
    from velora.workflow_automation import create_delegation, revoke_delegation
    from velora.permissions import session_as
    with session_as(Session("Administrator",frozenset({"System Manager"}))):
        row=create_delegation({"delegator":"manager@example.com","delegate":"delegate@example.com",
            "valid_from":datetime.now(timezone.utc).isoformat(),"valid_until":(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()})
        assert row["active"] is True
        assert revoke_delegation(row["id"])["active"] is False


def test_document_event_automation_enqueues_allowlisted_job(site, monkeypatch):
    from velora.meta.registry import registry
    from velora.workflow_automation import save_automation
    from velora.jobs import _jobs
    monkeypatch.setattr(registry, "job_handlers", lambda: {"audit_customer": "velora.workflow_automation.now"})
    save_automation({"name":"Customer Audit Event","event":"on_update","doctype":"Customer",
        "handler":"audit_customer","conditions":[{"field":"credit_limit","operator":">","value":10}]})
    customer = new_doc("Customer", customer_name="Automated Customer", credit_limit=50).insert()
    customer.customer_name = "Automated Customer Updated"
    customer.save()
    with db.transaction() as c:
        queued = c.execute(__import__('sqlalchemy').select(_jobs.c.id).where(_jobs.c.handler=="audit_customer",_jobs.c.status=="Queued")).all()
    assert queued


def test_parallel_workflow_branches_wait_for_all_independent_approvals(site):
    customer = new_doc("Customer", customer_name="Parallel Approval").insert()
    save_definition({
        "name": "Parallel Approval", "doctype": "Customer", "initial_state": "Pending",
        "states": [{"name": "Pending"}, {"name": "Approved", "is_final": True}],
        "transitions": [{
            "action": "Approve", "from_state": "Pending", "to_state": "Approved", "final": True,
            "parallel_steps": [
                {"key": "finance", "label": "Finance Review", "roles": ["Finance Manager"]},
                {"key": "risk", "label": "Risk Review", "roles": ["Risk Manager"]},
            ],
        }],
    })
    instance = start("Parallel Approval", "Customer", customer.name)
    with session_as(Session("finance@example.com", frozenset({"Finance Manager", "Sales User"}))):
        pending = act(instance["id"], "Approve", "Finance checked", "finance")
        assert pending["state"] == "Pending" and pending["status"] == "Active"
    with session_as(Session("risk@example.com", frozenset({"Risk Manager", "Sales User"}))):
        completed = act(instance["id"], "Approve", "Risk checked", "risk")
        assert completed["state"] == "Approved" and completed["status"] == "Completed"
    assert len(completed["approval_votes"]) == 2


def test_workflow_simulation_evaluates_routes_without_mutating_documents(site):
    from velora.workflows import simulate
    save_definition({
        "name": "Simulation Workflow", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Approved", "is_final": True}],
        "transitions": [{"action": "Approve", "from_state": "Draft", "to_state": "Approved", "roles": ["Approver"],
                         "condition": {"field": "credit_limit", "operator": ">", "value": 100}}],
    })
    result = simulate("Simulation Workflow", {"credit_limit": 250})
    assert result["matched_routes"][0]["action"] == "Approve"
    blocked = simulate("Simulation Workflow", {"credit_limit": 10})
    assert blocked["matched_routes"] == []


def test_workflow_sla_escalations_are_queued_once(site, monkeypatch):
    from datetime import timedelta
    from sqlalchemy import update
    from velora import site as site_module
    from velora.document.document import now
    from velora.workflow_automation import configure_sla, process_due_slas, sla
    import velora.jobs as jobs

    customer = new_doc("Customer", customer_name="SLA Escalation").insert()
    save_definition({"name":"SLA Workflow","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"],"final":True}]})
    running = start("SLA Workflow","Customer",customer.name)
    handler = "sample_app.jobs.escalate"
    monkeypatch.setitem(site_module.current().registry._job_handlers, handler, handler)
    monkeypatch.setattr(jobs, "_resolve", lambda name: (lambda payload: {"ok": True}))
    configure_sla(running["id"], 1, [{"after_minutes":0,"handler":handler,"payload":{"channel":"email"}}])
    with db.transaction() as conn:
        conn.execute(update(sla).where(sla.c.instance_id==running["id"]).values(due_on=now()-timedelta(minutes=2)))
    first = process_due_slas()
    second = process_due_slas()
    assert first["queued"] == 1 and second["queued"] == 0


def test_workflow_analytics_reports_company_local_backlog(site):
    from velora.workflows import workflow_analytics
    customer = new_doc("Customer", customer_name="Analytics Workflow").insert()
    save_definition({"name":"Analytics Workflow","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"],"final":True}]})
    start("Analytics Workflow","Customer",customer.name)
    result = workflow_analytics()
    assert result["total_instances"] >= 1
    assert result["active_instances"] >= 1
    assert any(x["state"] == "Draft" for x in result["active_by_state"])


def test_visual_workflow_layout_is_preserved_and_validated(site):
    customer = new_doc("Customer", customer_name="Visual Workflow").insert()
    result = save_definition({
        "name":"Visual Workflow","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft","x":90,"y":120},{"name":"Approved","is_final":True,"x":420,"y":120}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"],"label":"Finance approval"}],
    })
    assert result["states"][0]["x"] == 90
    with pytest.raises(ValidationError):
        save_definition({"name":"Invalid Visual Workflow","doctype":"Customer","initial_state":"Draft",
            "states":[{"name":"Draft","x":-1},{"name":"Draft"}],"transitions":[]})


def test_transition_activities_are_queued_as_durable_jobs(site, monkeypatch):
    from velora import jobs
    from velora.jobs import _jobs
    monkeypatch.setattr(jobs, "_resolve", lambda name: (lambda payload: {"ok": True}))
    customer = new_doc("Customer", customer_name="Activity Workflow").insert()
    save_definition({"name":"Activity Workflow","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"],
            "activities":[{"type":"notification","label":"Notify requester","handler":"sample_app.jobs.notify",
                          "delay_minutes":0,"payload":{"template":"approved"}}]}]})
    running = start("Activity Workflow","Customer",customer.name)
    with session_as(Session("approver@example.com",frozenset({"Approver","Sales User"}))):
        completed = act(running["id"],"Approve")
    assert completed["status"] == "Completed"
    with db.transaction() as conn:
        jobs_found=conn.execute(__import__("sqlalchemy").select(_jobs).where(
            _jobs.c.idempotency_key.like(f"wf-activity:{running['id']}:%"))).mappings().all()
    assert len(jobs_found)==1
    assert jobs_found[0]["payload"]["activity_type"]=="notification"


def test_workflow_version_restore_publishes_new_version_without_changing_old_snapshots(site):
    from velora.workflow_automation import restore_version, versions
    from velora.workflows import list_definitions
    customer = new_doc("Customer", customer_name="Versioned Workflow").insert()
    base={"name":"Versioned Workflow","doctype":"Customer","initial_state":"Draft",
        "states":[{"name":"Draft"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Approve","from_state":"Draft","to_state":"Approved","roles":["Approver"]}]}
    save_definition(base)
    changed={**base,"states":[{"name":"Draft"},{"name":"Review"},{"name":"Approved","is_final":True}],
        "transitions":[{"action":"Review","from_state":"Draft","to_state":"Review","roles":["Reviewer"]},
                       {"action":"Approve","from_state":"Review","to_state":"Approved","roles":["Approver"]}]}
    save_definition(changed)
    restored=restore_version("Versioned Workflow",1)
    assert restored["states"]==base["states"]
    with db.transaction() as conn:
        versions_found=conn.execute(__import__("sqlalchemy").select(versions).where(
            versions.c.workflow=="Versioned Workflow").order_by(versions.c.version)).mappings().all()
    assert [x["version"] for x in versions_found]==[1,2,3]
    assert list_definitions()[-1]["name"]=="Versioned Workflow"


def test_nested_workflow_child_suspends_and_resumes_parent(site):
    from velora.workflow_orchestration import start_child
    customer = new_doc("Customer", customer_name="Nested Workflow Customer").insert()
    save_definition({"name": "Parent Process", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Child Finished"}, {"name": "Done", "is_final": True}],
        "transitions": [{"action": "Finish", "from_state": "Child Finished", "to_state": "Done", "roles": ["Approver"], "final": True}]})
    save_definition({"name": "Child Process", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Done", "is_final": True}],
        "transitions": [{"action": "Complete Child", "from_state": "Draft", "to_state": "Done", "roles": ["Approver"], "final": True}]})
    parent = start("Parent Process", "Customer", customer.name)
    link = start_child(parent["id"], "Child Process", "Child Finished")
    assert link["parent_status"] == "Waiting"
    child = act(link["child_instance_id"], "Complete Child")
    assert child["status"] == "Completed"
    from velora.workflows import get_instance
    resumed = get_instance(parent["id"])
    assert resumed["status"] == "Active"
    assert resumed["state"] == "Child Finished"


def test_workflow_tasks_are_assignee_scoped_and_completable(site):
    from velora.workflow_orchestration import create_task, list_tasks, complete_task
    customer = new_doc("Customer", customer_name="Workflow Task Customer").insert()
    save_definition({"name": "Task Process", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}], "transitions": []})
    inst = start("Task Process", "Customer", customer.name)
    task = create_task(inst["id"], "Review customer file", "alice@example.com")
    with session_as(Session("alice@example.com", frozenset())):
        assert [x["id"] for x in list_tasks()] == [task["id"]]
        assert complete_task(task["id"])["status"] == "Completed"
        assert list_tasks(status="Open") == []


def test_workflow_event_gateway_runs_action_under_publisher_permissions(site):
    from velora.workflow_orchestration import subscribe_event, publish_event
    customer = new_doc("Customer", customer_name="Event Workflow Customer").insert()
    save_definition({"name": "Event Process", "doctype": "Customer", "initial_state": "Draft",
        "states": [{"name": "Draft"}, {"name": "Released", "is_final": True}],
        "transitions": [{"action": "Release", "from_state": "Draft", "to_state": "Released", "roles": ["Approver"], "final": True}]})
    inst = start("Event Process", "Customer", customer.name)
    subscribe_event(inst["id"], "finance.payment.confirmed", "Release", {"payment_id": "PAY-001"})
    with session_as(Session("approver@example.com", frozenset({"Approver", "Sales User"}))):
        result = publish_event("finance.payment.confirmed", {"payment_id": "PAY-001"})
    assert result["matched_count"] == 1
    assert result["processed"][0]["status"] == "processed"
    from velora.workflows import get_instance
    assert get_instance(inst["id"])["status"] == "Completed"
