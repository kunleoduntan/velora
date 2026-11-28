import json
import pytest
from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
from velora_projectone.projectone.integrations.native_schedule import (
    build_live_schedule, create_schedule_change_request, apply_approved_schedule_change,
)

ACTOR = AuthenticatedActor("manager-1", "COMP-1", frozenset({"Project Manager"}),
    frozenset({"projectone.task.update", "projectone.project.read", "projectone.task_dependency.read",
               "projectone.task.read", "projectone.baseline.read", "projectone.change_request.create",
               "projectone.change_request.read", "project_change_request.submit_for_approval"}))

class Repo:
    def __init__(self):
        self.projects = {"P-1": {"name":"P-1", "project_name":"Alpha", "start_date":"2026-12-01", "company":"COMP-1"}}
        self.tasks = {
            "T-1": {"name":"T-1", "project":"P-1", "title":"Design", "duration_days":3, "planned_start":"2026-12-01", "version":1, "company":"COMP-1"},
            "T-2": {"name":"T-2", "project":"P-1", "title":"Build", "duration_days":4, "planned_start":"2026-12-04", "version":1, "company":"COMP-1"},
        }
        self.deps = [{"name":"D-1", "project":"P-1", "predecessor":"T-1", "successor":"T-2", "relationship":"Finish to Start", "lag_days":0, "active":1}]
        self.baselines = []
        self.requests = {}
    def get(self, actor, doctype, name):
        source = {"Project":self.projects,"Project Task":self.tasks,"Project Change Request":self.requests}.get(doctype,{})
        return dict(source[name]) if name in source else None
    def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
        source = {"Project Task":list(self.tasks.values()),"Task Dependency":self.deps,"Project Baseline":self.baselines}.get(doctype,[])
        return [dict(x) for x in source if all(x.get(k)==v for k,v in (filters or {}).items())][offset:offset+limit]
    def insert(self, actor, doctype, document, *, idempotency_key, trusted_fields=None):
        row={**document, **(trusted_fields or {}), "approval_status":"Draft", "schedule_applied":0,
             "name":"CR-1", "version":1, "owner":actor.actor_id, "company":actor.company_id}
        self.requests[row["name"]]=row
        return dict(row)

class Bridge:
    def __init__(self): self.repo=Repo(); self.workflow=[]; self.permissions=[]
    def document_repository(self): return self.repo
    def assert_permission(self, actor, permission, *, project_id=None): self.permissions.append((permission,project_id))
    def workflow_action(self, actor, doctype, name, action, evidence):
        self.workflow.append((doctype,name,action,evidence))
        row=self.repo.requests[name]; row["approval_status"]="Pending Approval"
        return {"status":"submitted"}


def test_live_schedule_loads_native_tasks_and_dependencies():
    bridge=Bridge()
    result=build_live_schedule(bridge.repo, ACTOR, "P-1")
    assert result["source"].startswith("Velora native")
    assert len(result["schedule"]["gantt_rows"]) == 2
    assert result["schedule"]["gantt_rows"][1]["early_start_date"] == "2026-12-04"
    assert result["read_only"] is True


def test_live_schedule_rejects_cross_project_dependency():
    bridge=Bridge(); bridge.repo.deps[0]["predecessor"]="P-OTHER"
    with pytest.raises(ValueError, match="outside the selected project"):
        build_live_schedule(bridge.repo, ACTOR, "P-1")


def test_schedule_change_request_creates_impact_evidence_and_submits_workflow():
    bridge=Bridge()
    result=create_schedule_change_request(bridge, ACTOR, "P-1", task_id="T-1",
        proposed_start_offset=2, reason="Client approval delayed the design start.",
        title="Move design start", idempotency_key="req-001")
    assert result["change_request"]["approval_status"] == "Pending Approval"
    assert result["persisted_schedule_changes"] is False
    assert bridge.workflow[0][2] == "submit_for_approval"
    payload=json.loads(result["change_request"]["schedule_change_payload"])
    assert {x["task"] for x in payload["task_updates"]} == {"T-1","T-2"}
    assert bridge.repo.tasks["T-1"]["planned_start"] == "2026-12-01"


def test_schedule_change_request_rejects_short_reason():
    bridge=Bridge()
    with pytest.raises(ValueError, match="at least 10"):
        create_schedule_change_request(bridge, ACTOR, "P-1", task_id="T-1",
            proposed_start_offset=2, reason="late", title="Move", idempotency_key="req-002")


def test_apply_approved_schedule_change_requires_host_bridge_ports():
    class MinimalBridge:
        def document_repository(self):
            class R:
                def get(self,*args): return {"name":"CR-1","project":"P-1","approval_status":"Pending Approval"}
            return R()
    with pytest.raises(ValueError, match="Only an approved"):
        apply_approved_schedule_change(MinimalBridge(), ACTOR, "CR-1")

class TxManager:
    class Context:
        def __enter__(self): return object()
        def __exit__(self, *args): return False
    def transaction(self): return self.Context()

class Engine:
    def __init__(self, rows): self.rows=rows
    def get(self, session, doctype, name, company):
        row=self.rows.get((doctype,name))
        return dict(row) if row and row.get("company")==company else None
    def update_if_version(self, session, doctype, name, company, document, expected_version, actor_id):
        row=self.get(session,doctype,name,company)
        if not row or row.get("version") != expected_version: raise RuntimeError("version conflict")
        row.update(document); row["version"] += 1; row["modified_by"]=actor_id
        self.rows[(doctype,name)]=row
        return dict(row)

class Audit:
    def __init__(self): self.events=[]
    def append(self, session, **event): self.events.append(event)

class Idem:
    def __init__(self): self.cache={}
    def execute(self, session, company, key, digest, operation):
        old=self.cache.get((company,key))
        if old:
            if old[0] != digest: raise ValueError("idempotency conflict")
            return old[1]
        result=operation(); self.cache[(company,key)]=(digest,result); return result

class ApplyBridge:
    def __init__(self):
        rows={
          ("Project Change Request","CR-APP"): {"name":"CR-APP","project":"P-1","company":"COMP-1","version":1,"approval_status":"Approved","schedule_applied":0,"schedule_change_payload":json.dumps({"task_updates":[{"task":"T-1","expected_version":1,"planned_start":"2026-12-03","planned_finish":"2026-12-07"},{"task":"T-2","expected_version":1,"planned_start":"2026-12-08","planned_finish":"2026-12-11"}]})},
          ("Project Task","T-1"): {"name":"T-1","project":"P-1","company":"COMP-1","version":1,"planned_start":"2026-12-01","planned_finish":"2026-12-03"},
          ("Project Task","T-2"): {"name":"T-2","project":"P-1","company":"COMP-1","version":1,"planned_start":"2026-12-04","planned_finish":"2026-12-09"},
        }
        self.document_engine=Engine(rows); self.transaction_manager=TxManager(); self.audit_service=Audit(); self.idempotency_store=Idem()
    def document_repository(self):
        class R:
            def __init__(self, bridge): self.bridge=bridge
            def get(self, actor, doctype, name):
                return self.bridge.document_engine.get(None,doctype,name,actor.company_id)
        return R(self)
    def assert_permission(self, actor, permission, *, project_id=None):
        assert actor.company_id=="COMP-1" and permission in {"projectone.task.update", "projectone.schedule.apply"} and project_id=="P-1"


def test_apply_approved_schedule_change_updates_tasks_atomically_and_audits():
    bridge=ApplyBridge()
    result=apply_approved_schedule_change(bridge,ACTOR,"CR-APP")
    assert result["applied"] is True and result["updated_tasks"] == ["T-1","T-2"]
    assert bridge.document_engine.rows[("Project Task","T-1")]["planned_start"] == "2026-12-03"
    assert bridge.document_engine.rows[("Project Change Request","CR-APP")]["schedule_applied"] == 1
    assert len(bridge.audit_service.events)==3


def test_apply_approved_schedule_change_is_idempotent():
    bridge=ApplyBridge()
    first=apply_approved_schedule_change(bridge,ACTOR,"CR-APP")
    second=apply_approved_schedule_change(bridge,ACTOR,"CR-APP")
    assert first["applied"] and second["replayed"] is True
    assert len(bridge.audit_service.events)==3


def test_schedule_change_request_rejects_no_effect_constraint():
    bridge=Bridge()
    with pytest.raises(ValueError, match="does not change any task dates"):
        create_schedule_change_request(bridge, ACTOR, "P-1", task_id="T-2",
            proposed_start_offset=3, reason="A sufficiently detailed reason for no change.",
            title="No effect", idempotency_key="req-noop")


def test_schedule_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app=FastAPI(); install_routes(app,None,lambda request, operation: operation())
    routes={(route.path, tuple(sorted(route.methods or []))) for route in app.routes}
    assert ("/api/projectone/schedule/projects/{project_id}/live", ("GET",)) in routes
    assert ("/api/projectone/schedule/projects/{project_id}/tasks", ("POST",)) in routes
    assert ("/api/projectone/schedule/tasks/{task_id}", ("PUT",)) in routes
    assert ("/api/projectone/schedule/projects/{project_id}/dependencies", ("POST",)) in routes
    assert ("/api/projectone/schedule/change-requests", ("POST",)) in routes
    assert ("/api/projectone/schedule/change-requests/{name}/apply-approved", ("POST",)) in routes


def test_live_schedule_rejects_invalid_calendar_configuration():
    bridge=Bridge()
    with pytest.raises(ValueError, match="working_weekdays"):
        build_live_schedule(bridge.repo, ACTOR, "P-1", working_weekdays=(0,0,8))


class RollbackTxManager:
    def __init__(self, engine, audit): self.engine=engine; self.audit=audit
    class Context:
        def __init__(self, parent): self.parent=parent
        def __enter__(self):
            import copy
            self.rows=copy.deepcopy(self.parent.engine.rows)
            self.events=copy.deepcopy(self.parent.audit.events)
            return object()
        def __exit__(self, exc_type, exc, tb):
            if exc_type:
                self.parent.engine.rows=self.rows
                self.parent.audit.events=self.events
            return False
    def transaction(self): return self.Context(self)


def test_stale_task_version_rolls_back_all_schedule_updates_and_audit():
    bridge=ApplyBridge()
    bridge.transaction_manager=RollbackTxManager(bridge.document_engine,bridge.audit_service)
    # The second task changed after the approval request was prepared.
    bridge.document_engine.rows[("Project Task","T-2")]["version"]=2
    before=bridge.document_engine.rows[("Project Task","T-1")]["planned_start"]
    with pytest.raises(Exception, match="changed after the schedule request"):
        apply_approved_schedule_change(bridge,ACTOR,"CR-APP")
    assert bridge.document_engine.rows[("Project Task","T-1")]["planned_start"] == before
    assert bridge.audit_service.events == []
    assert bridge.document_engine.rows[("Project Change Request","CR-APP")]["schedule_applied"] == 0


def test_live_schedule_uses_project_default_calendar_and_holidays():
    class CalendarRepo(Repo):
        def __init__(self):
            super().__init__()
            self.calendars = [{"name":"CAL-1", "calendar_name":"Nigeria Office Calendar",
                "active":1, "is_default":1, "working_weekdays":"0,1,2,3,4",
                "holiday_dates":"[\"2026-12-04\"]"}]
        def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
            if doctype == "Resource Calendar":
                return [dict(x) for x in self.calendars if all(x.get(k)==v for k,v in (filters or {}).items())][offset:offset+limit]
            return super().list(actor, doctype, filters=filters, limit=limit, offset=offset)
    repo=CalendarRepo()
    result=build_live_schedule(repo, ACTOR, "P-1")
    assert result["calendar"]["calendar_name"] == "Nigeria Office Calendar"
    assert result["calendar"]["holidays"] == ["2026-12-04"]
    assert result["schedule"]["gantt_rows"][1]["early_start_date"] == "2026-12-07"


def test_dependency_graph_rejects_cycles_before_persistence():
    from velora_projectone.projectone.integrations.native_schedule import validate_dependency_graph
    tasks=[{"name":"T-1","duration_days":2},{"name":"T-2","duration_days":2}]
    existing=[{"name":"D-1","predecessor":"T-1","successor":"T-2",
               "relationship":"Finish to Start","lag_days":0,"active":1}]
    with pytest.raises(ValueError, match="cycle"):
        validate_dependency_graph(tasks, existing, {"predecessor":"T-2","successor":"T-1",
            "relationship":"Finish to Start","lag_days":0,"active":1})


def test_dependency_graph_allows_editing_existing_edge_without_self_conflict():
    from velora_projectone.projectone.integrations.native_schedule import validate_dependency_graph
    tasks=[{"name":"T-1","duration_days":2},{"name":"T-2","duration_days":2},{"name":"T-3","duration_days":1}]
    existing=[{"name":"D-1","predecessor":"T-1","successor":"T-2",
               "relationship":"Finish to Start","lag_days":0,"active":1}]
    assert validate_dependency_graph(tasks, existing, {"name":"D-1","predecessor":"T-1",
        "successor":"T-3","relationship":"Start to Start","lag_days":1,"active":1}, exclude_id="D-1")


def test_dependency_edit_route_is_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app=FastAPI(); install_routes(app,None,lambda request, operation: operation())
    assert any(route.path=="/api/projectone/schedule/dependencies/{dependency_id}" and "PUT" in (route.methods or set()) for route in app.routes)


def test_live_schedule_uses_explicit_project_calendar():
    class LinkedCalendarRepo(Repo):
        def __init__(self):
            super().__init__()
            self.projects['P-1']['resource_calendar']='CAL-WEEKEND'
            self.calendars={'CAL-WEEKEND':{"name":"CAL-WEEKEND","calendar_name":"Six Day Week",
                "active":1,"working_weekdays":"0,1,2,3,4,5","holiday_dates":"2026-12-05"}}
        def get(self, actor, doctype, name):
            if doctype == "Resource Calendar":
                return dict(self.calendars[name]) if name in self.calendars else None
            return super().get(actor, doctype, name)
        def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
            if doctype == "Resource Calendar": return []
            return super().list(actor, doctype, filters=filters, limit=limit, offset=offset)
    result=build_live_schedule(LinkedCalendarRepo(), ACTOR, "P-1")
    assert result["calendar"]["name"] == "CAL-WEEKEND"
    assert result["calendar"]["working_weekdays"] == [0,1,2,3,4,5]
    assert result["calendar"]["holidays"] == ["2026-12-05"]


def test_live_schedule_rejects_multiple_default_calendars():
    class AmbiguousCalendarRepo(Repo):
        def list(self, actor, doctype, *, filters=None, limit=100, offset=0):
            if doctype == "Resource Calendar":
                return [{"name":"CAL-A","active":1,"is_default":1},
                        {"name":"CAL-B","active":1,"is_default":1}]
            return super().list(actor, doctype, filters=filters, limit=limit, offset=offset)
    with pytest.raises(ValueError, match="Multiple active default"):
        build_live_schedule(AmbiguousCalendarRepo(), ACTOR, "P-1")
