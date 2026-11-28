import pytest
from velora_projectone.projectone.integrations.native_bridge import (
    NativeVeloraBridge, NativeIntegrationRegistry,
)
from velora_projectone.projectone.integrations.host_contracts import AuthenticatedActor
from velora_projectone.projectone.integrations.health import integration_health


class Docs:
    def get(self, session, doctype, name, company): return {"name": name, "company": company, "status": "Draft", "owner": "u0", "version": 1}
    def list(self,*a): pass
    def insert(self,*a): pass
    def update_if_version(self,*a): pass
class Tx:
    class Context:
        def __enter__(self): return object()
        def __exit__(self, *args): return False
    def transaction(self): return self.Context()
class Auth:
    def assert_permission(self,*a,**k): pass
    def get_permitted_fields(self, actor, doctype, action, **kwargs):
        return {"name", "company", "status", "owner", "version", "project_name", "project"}
class Audit:
    def append(self,*a,**k): pass
    def list_for_project(self,*a,**k): pass
class Idem:
    def execute(self,*a,**k): pass
class Sources:
    def get(self,*a): return None
class Workflow:
    def submit(self,*a,**k): return {"status":"submitted"}


def bridge(**overrides):
    from velora_projectone.projectone.integrations.native_bridge import NativeIntegrationCapabilities
    ports = dict(document_engine=Docs(), transaction_manager=Tx(), authorization=Auth(),
                 audit_service=Audit(), idempotency_store=Idem(), source_registry=Sources(),
                 workflow_service=Workflow(), capability_attestation=NativeIntegrationCapabilities(
                     True, True, True, True, True, True, True))
    ports.update(overrides)
    return NativeVeloraBridge(**ports)


def test_bridge_requires_all_host_ports():
    with pytest.raises(TypeError):
        bridge(source_registry=object())


def test_bridge_rejects_missing_capability_attestation():
    with pytest.raises(TypeError):
        NativeVeloraBridge(document_engine=Docs(), transaction_manager=Tx(), authorization=Auth(),
                           audit_service=Audit(), idempotency_store=Idem(), source_registry=Sources(),
                           workflow_service=Workflow())


def test_registry_fails_closed_until_configured():
    registry = NativeIntegrationRegistry()
    assert registry.readiness()["production_ready"] is False
    registry.configure(bridge())
    assert registry.readiness()["production_ready"] is True


def test_registry_rejects_non_native_bridge():
    with pytest.raises(TypeError):
        NativeIntegrationRegistry().configure(object())


def test_workflow_requires_trusted_actor():
    with pytest.raises(PermissionError):
        bridge().workflow_action({"actor_id":"fake"}, "Project", "P-1", "approve")


def test_workflow_calls_authorization_and_host_workflow():
    b = bridge()
    actor = AuthenticatedActor("u1", "c1", frozenset({"Project Manager"}))
    assert b.workflow_action(actor, "Project", "P-1", "approve", {"decision": "approved", "note": "reviewed"})["workflow"]["status"] == "submitted"


def test_integration_health_never_claims_unconnected_ready():
    report = integration_health({"production_ready": True, "sources": {"accounting":{"configured":True}}})
    assert report["production_ready"] is False
    assert report["sources"]["accounting"]["write_access"] is False

class UnitOfWork:
    class _Context:
        def __enter__(self): return object()
        def __exit__(self, *args): return False
    def transaction(self): return self._Context()
class ProjectDocs:
    def __init__(self): self.rows = {}
    def get(self, session, doctype, name, company):
        row = self.rows.get(name)
        return row if row and row.get("company") == company else None
    def list(self, session, doctype, company, filters, limit, offset):
        rows = [r for r in self.rows.values() if r.get("company") == company]
        if filters.get("status"):
            rows = [r for r in rows if r.get("status") == filters["status"]]
        return rows[offset:offset+limit]
    def insert(self, session, doctype, document, actor_id):
        row = dict(document, name="PRJ-1", version=1, company="C-1")
        self.rows[row["name"]] = row
        return row
    def update_if_version(self, session, doctype, name, company, document, expected_version, actor_id):
        old = self.get(session, doctype, name, company)
        if not old or old["version"] != expected_version: raise RuntimeError("conflict")
        row = dict(old, **document, version=expected_version+1)
        self.rows[name] = row
        return row
class AuditLog:
    def __init__(self): self.events=[]
    def append(self, session, **event): self.events.append(event)
    def list_for_project(self, session, project_id, company, *, limit):
        return [e for e in self.events if e["project_id"] == project_id and e["company_id"] == company][:limit]
class Idempotency:
    def execute(self, session, company, key, request_hash, operation): return operation()


def test_native_bridge_composes_tenant_scoped_project_repository():
    from velora_projectone.projectone.integrations.native_bridge import NativeIntegrationCapabilities
    docs, audit = ProjectDocs(), AuditLog()
    b = NativeVeloraBridge(document_engine=docs, transaction_manager=UnitOfWork(),
        authorization=Auth(), audit_service=audit, idempotency_store=Idempotency(),
        source_registry=Sources(), workflow_service=Workflow(),
        capability_attestation=NativeIntegrationCapabilities(True,True,True,True,True,True,True))
    repo = b.project_repository()
    actor = AuthenticatedActor("U-1", "C-1", frozenset(), frozenset({
        "projectone.project.create", "projectone.project.read", "projectone.portfolio.read",
        "projectone.project.audit.read", "projectone.project.update"}))
    saved = repo.insert(actor, {"project_name":"Test"})
    assert saved["name"] == "PRJ-1"
    assert repo.get(actor, "PRJ-1")["project_name"] == "Test"
    assert len(repo.audit_events(actor, "PRJ-1")) == 1

def test_native_bridge_composes_core_document_repository():
    from velora_projectone.projectone.integrations.native_documents import NativeDocumentRepository
    repository = bridge().document_repository()
    assert isinstance(repository, NativeDocumentRepository)
