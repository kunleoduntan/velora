import pytest
from velora_projectone.projectone.integrations.native_documents import NativeDocumentRepository
from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
from velora_projectone.projectone.services.persistence import VersionConflict


class Uow:
    class Tx:
        def __enter__(self): return object()
        def __exit__(self, *args): return False
    def transaction(self): return self.Tx()

class Docs:
    def __init__(self): self.rows = {}; self.counter = 0
    def get(self, session, doctype, name, company):
        row = self.rows.get((doctype, name))
        return dict(row) if row else None
    def list(self, session, doctype, company, filters, limit, offset):
        rows = [dict(v) for (dt, _), v in self.rows.items() if dt == doctype]
        for key, value in filters.items(): rows = [r for r in rows if r.get(key) == value]
        return rows[offset:offset+limit]
    def insert(self, session, doctype, document, actor_id):
        self.counter += 1; name = f"{doctype[:3].upper()}-{self.counter}"
        row = dict(document, name=name, version=1, owner=actor_id)
        self.rows[(doctype, name)] = row
        return dict(row)
    def update_if_version(self, session, doctype, name, company, document, expected_version, actor_id):
        old = self.get(session, doctype, name, company)
        if not old or old["version"] != expected_version: raise RuntimeError("conflict")
        row = dict(old, **document, version=expected_version + 1, modified_by=actor_id)
        self.rows[(doctype, name)] = row
        return dict(row)

class Auth:
    def __init__(self): self.calls=[]; self.denied_fields=set(); self.hidden_fields=set()
    def assert_permission(self, actor, permission, *, company_id, project_id=None):
        self.calls.append((permission, company_id, project_id))
        if company_id != actor.company_id: raise PermissionError()
    def get_permitted_fields(self, actor, doctype, action, *, company_id, project_id=None):
        if company_id != actor.company_id: raise PermissionError()
        # Test adapter models Frappe's DocField.permlevel result, not field types.
        all_metadata_fields = {
            "name", "company", "owner", "version", "modified", "creation", "project_name", "status", "project",
            "description", "budget", "currency", "transaction_price", "recognition_method", "approval_status",
            "subject", "title", "task_code", "change_code", "requested_by", "schedule_change_payload",
            "schedule_applied", "predecessor", "successor", "relationship", "lag_days", "active",
            "contract_reference", "obligation_code", "allocated_transaction_price", "recognition_over_time",
            "accounting_conclusion_reference", "commercial_margin", "approved_by", "approved_on",
            "baseline_name", "performance_obligation", "period_end", "control_transfer_confirmed",
            "cumulative_actual_cost", "forecast_total_cost", "prior_cumulative_revenue", "cumulative_revenue",
            "current_period_revenue", "cumulative_cost", "current_period_cost", "cumulative_profit",
            "current_period_profit", "forecast_total_profit", "forecast_margin_percent",
            "potential_onerous_contract_loss", "source_watermark", "progress_percent",
        }
        return all_metadata_fields - (self.denied_fields if action != "read" else self.hidden_fields)

class Audit:
    def __init__(self): self.events=[]
    def append(self, session, **event): self.events.append(event)
    def list_for_project(self, *a, **k): return []

class Idem:
    def __init__(self): self.results={}
    def execute(self, session, company, key, request_hash, operation):
        old = self.results.get((company,key))
        if old:
            if old[0] != request_hash: raise ValueError("idempotency conflict")
            return old[1]
        result = operation(); self.results[(company,key)] = (request_hash,result); return result

@pytest.fixture
def setup_repo():
    docs, auth, audit, idem = Docs(), Auth(), Audit(), Idem()
    repo = NativeDocumentRepository(document_engine=docs, transaction_manager=Uow(),
        authorization=auth, audit_service=audit, idempotency_store=idem)
    actor = AuthenticatedActor("U-1", "CO-1", frozenset(), frozenset())
    return repo, actor, docs, auth, audit

def test_insert_is_idempotent(setup_repo):
    repo, actor, docs, auth, audit = setup_repo
    a = repo.insert(actor, "Project", {"project_name":"Alpha"}, idempotency_key="create-1")
    b = repo.insert(actor, "Project", {"project_name":"Alpha"}, idempotency_key="create-1")
    assert a == b and "company" not in a
    assert len(docs.rows) == 1 and len(audit.events) == 1

def test_unknown_doctype_is_rejected_before_host_access(setup_repo):
    repo, actor, *_ = setup_repo
    with pytest.raises(ValueError): repo.list(actor, "User")

def test_list_filters_cannot_override_system_fields(setup_repo):
    repo, actor, *_ = setup_repo
    repo.insert(actor, "Project", {"project_name":"A", "status":"Draft"}, idempotency_key="a")
    assert len(repo.list(actor, "Project", filters={"status":"Draft"})) == 1
    with pytest.raises(ValueError): repo.list(actor, "Project", filters={"owner":"someone"})

def test_update_requires_version_and_records_audit(setup_repo):
    repo, actor, *_ , audit = setup_repo
    saved = repo.insert(actor, "Project", {"project_name":"A"}, idempotency_key="a")
    updated = repo.update(actor, "Project", saved["name"], {"project_name":"B"}, expected_version=1)
    assert updated["version"] == 2 and updated["project_name"] == "B"
    assert audit.events[-1]["action"] == "project.updated"
    with pytest.raises(VersionConflict):
        repo.update(actor, "Project", saved["name"], {"project_name":"C"}, expected_version=1)

def test_child_document_requires_project_scope_authorization(setup_repo):
    repo, actor, *_ = setup_repo
    row = repo.insert(actor, "Project Task", {"project":"PRJ-9", "subject":"Build"}, idempotency_key="task1")
    assert "company" not in row

def test_untrusted_actor_rejected(setup_repo):
    repo, *_ = setup_repo
    with pytest.raises(PermissionError): repo.list({"company_id":"CO-1"}, "Project")

def test_idempotency_key_reuse_with_different_payload_rejected(setup_repo):
    repo, actor, *_ = setup_repo
    repo.insert(actor, "Project", {"project_name":"A"}, idempotency_key="same")
    with pytest.raises(ValueError):
        repo.insert(actor, "Project", {"project_name":"B"}, idempotency_key="same")

def test_child_document_requires_parent_project(setup_repo):
    repo, actor, *_ = setup_repo
    with pytest.raises(ValueError):
        repo.insert(actor, "Project Task", {"subject":"No parent"}, idempotency_key="missing-parent")

def test_child_document_cannot_be_reparented_by_generic_update(setup_repo):
    repo, actor, *_ = setup_repo
    saved = repo.insert(actor, "Project Task", {"project":"PRJ-1", "title":"Task"}, idempotency_key="task")
    with pytest.raises(ValueError):
        repo.update(actor, "Project Task", saved["name"], {"project":"PRJ-2"}, expected_version=1)

def test_generic_crud_cannot_bypass_workflow_approval_or_schedule_dates(setup_repo):
    repo, actor, *_ = setup_repo
    with pytest.raises(ValueError, match="Workflow-controlled"):
        repo.insert(actor, "Project Change Request", {
            "project":"P-1", "change_code":"X", "title":"Forged approval",
            "approval_status":"Approved"
        }, idempotency_key="forged-approval")


def test_generic_crud_cannot_change_approved_baseline_or_task_dates(setup_repo):
    repo, actor, *_ = setup_repo
    task=repo.insert(actor,"Project Task",{"project":"P-1","task_code":"T-2","title":"Build"},idempotency_key="task-two")
    with pytest.raises(ValueError, match="Workflow-controlled"):
        repo.update(actor,"Project Task",task["name"],{"planned_start":"2026-12-02"},expected_version=1)
    baseline=repo.insert(actor,"Project Baseline",{"project":"P-1","baseline_name":"Initial"},idempotency_key="base-one")
    with pytest.raises(ValueError, match="Workflow-controlled"):
        repo.update(actor,"Project Baseline",baseline["name"],{"approval_status":"Approved"},expected_version=1)

def test_internal_schedule_fields_are_only_available_to_trusted_backend(setup_repo):
    repo, actor, docs, *_ = setup_repo
    saved = repo.insert(actor, "Project Change Request", {
        "project":"P-1", "change_code":"SCH-1", "title":"Schedule change"
    }, idempotency_key="schedule-1", trusted_fields={
        "schedule_change_payload":"{\"task_updates\":[]}", "schedule_applied":0
    })
    assert saved["approval_status"] == "Draft"
    assert saved["requested_by"] == actor.actor_id
    assert saved["schedule_change_payload"] == "{\"task_updates\":[]}"
    with pytest.raises(ValueError, match="Workflow-controlled"):
        repo.update(actor, "Project Change Request", saved["name"],
                    {"approval_status":"Approved"}, expected_version=1)
    docs.rows[("Project Change Request", saved["name"])]["approval_status"] = "Pending Approval"
    with pytest.raises(ValueError, match="no longer editable"):
        repo.update(actor, "Project Change Request", saved["name"],
                    {"title":"Tampered after submission"}, expected_version=1)

def test_task_dependency_is_enabled_for_tenant_scoped_native_persistence(setup_repo):
    repo, actor, *_ = setup_repo
    row=repo.insert(actor,"Task Dependency",{
        "project":"P-1","predecessor":"T-1","successor":"T-2",
        "relationship":"Finish to Start","lag_days":0,"active":1
    },idempotency_key="dependency-1")
    assert "company" not in row
    assert repo.get(actor,"Task Dependency",row["name"])["successor"] == "T-2"

def test_trusted_create_fields_cannot_forge_workflow_approval(setup_repo):
    repo, actor, *_ = setup_repo
    with pytest.raises(ValueError, match="unsupported fields"):
        repo.insert(actor,"Project Change Request",{
            "project":"P-1","change_code":"SCH-X","title":"Test"
        },idempotency_key="trusted-forgery",trusted_fields={"approval_status":"Approved"})


def test_authoritative_resource_profile_and_availability_exception_are_read_only(setup_repo):
    repo, actor, *_ = setup_repo
    for doctype, key in (("Resource Profile", "profile"), ("Resource Availability Exception", "exception")):
        with pytest.raises(PermissionError, match="authoritative read-only"):
            repo.insert(actor, doctype, {"company":"CO-1"}, idempotency_key=key)
        with pytest.raises(PermissionError, match="authoritative read-only"):
            repo.update(actor, doctype, "SOURCE-1", {"display_name":"Tamper"}, expected_version=1)


def test_financial_documents_are_native_tenant_scoped_and_recognition_values_are_trusted_only(setup_repo):
    repo, actor, docs, auth, audit = setup_repo
    obligation = repo.insert(actor, "Project Performance Obligation", {
        "project": "PRJ-1", "contract_reference": "CTR-1", "obligation_code": "PO-1",
        "description": "Implementation services", "currency": "NGN",
        "allocated_transaction_price": 1000000, "recognition_method": "Cost To Cost",
        "recognition_over_time": 1, "accounting_conclusion_reference": "FIN-MEMO-1",
    }, idempotency_key="obligation-1")
    assert "company" not in obligation
    assert obligation["status"] == "Draft"
    assert repo.get(actor, "Project Performance Obligation", obligation["name"])["project"] == "PRJ-1"
    with pytest.raises(ValueError, match="Calculated financial fields"):
        repo.insert(actor, "Project Revenue Recognition", {
            "project": "PRJ-1", "performance_obligation": obligation["name"],
            "period_end": "2026-11-30", "currency": "NGN", "progress_percent": 75,
        }, idempotency_key="forged-recognition")
    proposal = repo.insert(actor, "Project Revenue Recognition", {
        "project": "PRJ-1", "performance_obligation": obligation["name"],
        "period_end": "2026-11-30", "currency": "NGN",
    }, idempotency_key="recognition-1", trusted_fields={
        "transaction_price": 1000000, "recognition_method": "cost_to_cost",
        "recognition_over_time": True, "control_transfer_confirmed": False,
        "progress_percent": 50, "cumulative_actual_cost": 250000,
        "forecast_total_cost": 500000, "prior_cumulative_revenue": 0,
        "cumulative_revenue": 500000, "current_period_revenue": 500000,
        "cumulative_cost": 250000, "current_period_cost": 250000,
        "cumulative_profit": 250000, "current_period_profit": 250000,
        "forecast_total_profit": 500000, "forecast_margin_percent": 50,
        "potential_onerous_contract_loss": False, "source_watermark": "acct:2026-11-30:abc",
    })
    assert proposal["approval_status"] == "Pending Review"
    assert proposal["source_watermark"] == "acct:2026-11-30:abc"


def test_field_permissions_are_checked_on_writes_and_filter_reads(setup_repo):
    repo, actor, docs, auth, audit = setup_repo
    saved = repo.insert(actor, "Project", {"project_name": "Restricted"}, idempotency_key="field-test")
    assert repo.get(actor, "Project", saved["name"])["project_name"] == "Restricted"
    assert any(call[0] == "projectone.project.create" for call in auth.calls)


def test_field_level_read_and_write_permissions_are_enforced(setup_repo):
    repo, actor, docs, auth, audit = setup_repo
    saved = repo.insert(actor, "Project", {"project_name":"Restricted", "commercial_margin":42}, idempotency_key="field-perm")
    auth.hidden_fields.add("commercial_margin")
    visible = repo.get(actor, "Project", saved["name"])
    assert "commercial_margin" not in visible
    auth.denied_fields.add("commercial_margin")
    with pytest.raises(PermissionError, match="Permission level does not allow access"):
        repo.update(actor, "Project", saved["name"], {"commercial_margin":50}, expected_version=1)


def test_dashboard_support_documents_are_read_only_until_governed_commands_exist(setup_repo):
    repo, actor, *_ = setup_repo
    for doctype in ("Project Budget", "Project Quality Inspection", "Project Sprint", "Project User Story", "Project Timesheet", "Project Benefit"):
        with pytest.raises(PermissionError, match="authoritative read-only"):
            repo.insert(actor, doctype, {"project": "PRJ-1"}, idempotency_key=f"dash-{doctype}")
