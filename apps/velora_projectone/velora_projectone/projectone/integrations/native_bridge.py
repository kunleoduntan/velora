"""Production-oriented Velora integration composition root.

This module deliberately depends on injected host ports. It does not guess
Velora internals or silently fall back to an in-memory/test repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .host_contracts import HostCapabilities, AuthenticatedActor
from .host_adapter import VeloraProjectRepository
from .source_readers import ProjectOneReadIntegration


@dataclass(frozen=True)
class NativeIntegrationCapabilities:
    document_engine: bool
    transaction_manager: bool
    authorization_service: bool
    audit_service: bool
    idempotency_store: bool
    source_registry: bool
    workflow_service: bool

    def missing(self) -> list[str]:
        return [name for name, enabled in self.__dict__.items() if not enabled]

    def assert_complete(self) -> None:
        missing = self.missing()
        if missing:
            raise RuntimeError("Native Velora integration is incomplete: " + ", ".join(missing))


class NativeDocumentPort(Protocol):
    """Host document engine; every operation must include company scope."""
    def get(self, session: Any, doctype: str, name: str, company: str) -> dict | None: ...
    def list(self, session: Any, doctype: str, company: str, filters: dict,
             limit: int, offset: int) -> list[dict]: ...
    def insert(self, session: Any, doctype: str, document: dict, actor_id: str) -> dict: ...
    def update_if_version(self, session: Any, doctype: str, name: str, company: str,
                          document: dict, expected_version: int, actor_id: str) -> dict: ...


class NativeAuthorizationPort(Protocol):
    def assert_permission(self, actor: AuthenticatedActor, permission: str,
                          *, company_id: str, project_id: str | None = None) -> None: ...
    def get_permitted_fields(self, actor: AuthenticatedActor, doctype: str,
                             action: str, *, company_id: str,
                             project_id: str | None = None) -> set[str]: ...


class NativeWorkflowPort(Protocol):
    def submit(self, actor: AuthenticatedActor, doctype: str, name: str,
               action: str, evidence: dict | None = None) -> dict: ...


class NativeVeloraBridge:
    """Explicitly composed bridge to installed Velora host services.

    Supply concrete Velora implementations for all ports during app bootstrap.
    The adapter fails closed when a required production capability is absent.
    """
    def __init__(self, *, document_engine, transaction_manager, authorization,
                 audit_service, idempotency_store, source_registry, workflow_service,
                 capability_attestation: NativeIntegrationCapabilities):
        self.document_engine = document_engine
        self.transaction_manager = transaction_manager
        self.authorization = authorization
        self.audit_service = audit_service
        self.idempotency_store = idempotency_store
        self.source_registry = source_registry
        self.workflow_service = workflow_service
        if not isinstance(capability_attestation, NativeIntegrationCapabilities):
            raise TypeError("Deployment must provide explicit NativeIntegrationCapabilities attestation.")
        self._capability_attestation = capability_attestation
        self._validate()

    def _validate(self):
        required = {
            "document_engine": ("get", "list", "insert", "update_if_version"),
            "transaction_manager": ("transaction",),
            "authorization": ("assert_permission", "get_permitted_fields"),
            "audit_service": ("append", "list_for_project"),
            "idempotency_store": ("execute",),
            "source_registry": ("get",),
            "workflow_service": ("submit",),
        }
        for name, methods in required.items():
            obj = getattr(self, name)
            absent = [method for method in methods if not callable(getattr(obj, method, None))]
            if absent:
                raise TypeError(f"{name} missing required methods: {', '.join(absent)}")

    def capabilities(self) -> NativeIntegrationCapabilities:
        return self._capability_attestation

    def project_repository(self, *, require_production_capabilities: bool = True):
        """Compose the generic ProjectOne repository over injected Velora ports.

        The document engine remains responsible for mapping the Project DocType
        fields and enforcing company scope in its database query.
        """
        self.capabilities().assert_complete()
        bridge = _ProjectRepositoryBridge(self)
        repository = VeloraProjectRepository(bridge, require_production_capabilities=require_production_capabilities)
        return _ScopedNativeProjectRepository(self, repository)

    def document_repository(self):
        """Return tenant-scoped persistence for the approved core DocType set."""
        self.capabilities().assert_complete()
        from .native_documents import NativeDocumentRepository
        return NativeDocumentRepository(
            document_engine=self.document_engine,
            transaction_manager=self.transaction_manager,
            authorization=self.authorization,
            audit_service=self.audit_service,
            idempotency_store=self.idempotency_store,
        )

    def read_integration(self, *, max_records_per_source: int = 1000):
        if not self.capabilities().source_registry:
            raise RuntimeError("Source registry capability has not been attested by the deployment.")
        return ProjectOneReadIntegration(self.source_registry,
                                         max_records_per_source=max_records_per_source)

    def collect_dashboard_data(self, actor: AuthenticatedActor, *, project_id=None,
                               modified_since=None, limit=500):
        """Collect native ProjectOne and permitted upstream dashboard read models."""
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        from ..reports.dashboard_sources import collect_core_dashboard_data
        core = collect_core_dashboard_data(self.document_repository(), actor,
                                            project_id=project_id, limit=limit)
        data = dict(core["data"])
        provenance = {"projectone": core["metadata"]}
        denied = list(core["permission_denied_collections"])
        # External source access is opt-in through the authenticated actor's
        # integration permissions. The collection allowlist is server-owned.
        from .source_readers import SOURCE_COLLECTIONS
        if self.capabilities().source_registry:
            requests = {}
            for source_name, collections in SOURCE_COLLECTIONS.items():
                permission = f"projectone.integration.{source_name}.read"
                if permission in actor.permissions or "projectone.integration.read_all" in actor.permissions:
                    requests[source_name] = sorted(collections)
            if requests:
                external = self.read_integration(max_records_per_source=limit).collect(
                    actor, requests, project_id=project_id, modified_since=modified_since)
                for key, rows in external.get("data", {}).items():
                    if rows:
                        data[key] = rows
                provenance.update(external.get("provenance", {}))
        return {"data": data, "provenance": provenance,
                "permission_denied_collections": denied,
                "scope": {"company": actor.company_id, "project": project_id},
                "metadata": {"read_only": True, "source_of_truth": "ProjectOne and upstream source applications",
                             "currency_policy": "never aggregate mixed currencies"}}

    def assert_permission(self, actor: AuthenticatedActor, permission: str,
                          *, project_id: str | None = None):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        self.authorization.assert_permission(actor, permission,
                                             company_id=actor.company_id,
                                             project_id=project_id)

    def workflow_action(self, actor: AuthenticatedActor, doctype: str, name: str,
                        action: str, evidence: dict | None = None):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        from .native_documents import NativeDocumentRepository
        from ..services.workflow_lifecycle import validate_lifecycle_command
        repository = self.document_repository()
        document = repository.get_for_workflow(actor, doctype, name)
        if document is None:
            raise KeyError(name)
        # Child records have already passed the repository's project-scoped
        # authorization check. Portfolio/programme/project records are tenant scoped.
        validation = validate_lifecycle_command(doctype, action, document,
                                                actor.actor_id, evidence or {})
        self.assert_permission(actor, f"{doctype.lower().replace(' ', '_')}.{action}",
                               project_id=document.get("project") or (name if doctype == "Project" else None))
        result = self.workflow_service.submit(actor, doctype, name, action, evidence or {})
        return {"workflow": result, "validation": validation,
                "authority": "Velora host workflow service"}

    def pending_workflow_items(self, actor: AuthenticatedActor, *, limit: int = 100):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        self.assert_permission(actor, "projectone.workflow.inbox.read")
        reader = getattr(self.workflow_service, "list_pending", None)
        if not callable(reader):
            raise RuntimeError("The deployment workflow adapter does not provide an approval inbox.")
        return reader(actor, company_id=actor.company_id, limit=limit)


class _ScopedNativeProjectRepository:
    """Actor-scoped facade; never accepts caller-supplied actor/company strings."""
    def __init__(self, native: NativeVeloraBridge, repository: VeloraProjectRepository):
        self.native = native
        self.repository = repository

    def _actor(self, actor: AuthenticatedActor):
        if not isinstance(actor, AuthenticatedActor):
            raise PermissionError("Trusted Velora actor is required.")
        return actor

    def get(self, actor: AuthenticatedActor, project_id: str):
        actor = self._actor(actor)
        self.native.assert_permission(actor, "projectone.project.read", project_id=project_id)
        return self.repository.get(project_id, actor.company_id)

    def list(self, actor: AuthenticatedActor, *, status=None, limit=100, offset=0):
        actor = self._actor(actor)
        self.native.assert_permission(actor, "projectone.portfolio.read")
        return self.repository.list(actor.company_id, status=status, limit=limit, offset=offset)

    def insert(self, actor: AuthenticatedActor, document: dict):
        actor = self._actor(actor)
        self.native.assert_permission(actor, "projectone.project.create")
        if not isinstance(document, dict):
            raise TypeError("Project document must be an object.")
        safe = dict(document)
        safe.pop("company", None)
        return self.repository.insert(safe, actor_id=actor.actor_id, scope=actor.company_id)

    def update(self, actor: AuthenticatedActor, project_id: str, document: dict,
               *, expected_version: int, action="project.updated"):
        actor = self._actor(actor)
        self.native.assert_permission(actor, "projectone.project.update", project_id=project_id)
        if not isinstance(document, dict):
            raise TypeError("Project document must be an object.")
        return self.repository.update(project_id, actor.company_id, document,
                                      expected_version=expected_version,
                                      actor_id=actor.actor_id, action=action)

    def audit_events(self, actor: AuthenticatedActor, project_id: str, *, limit=100):
        actor = self._actor(actor)
        self.native.assert_permission(actor, "projectone.project.audit.read", project_id=project_id)
        return self.repository.audit_events(project_id, actor.company_id, limit=limit)


class _ProjectRepositoryBridge:
    """Narrow adapter exposing only the ProjectOne project repository ports."""
    def __init__(self, native: NativeVeloraBridge):
        self.native = native
        self.uow = native.transaction_manager
        self.projects = _ProjectDocumentAdapter(native.document_engine)
        self.audit = native.audit_service
        self.idempotency = native.idempotency_store

    def capabilities(self):
        return HostCapabilities(
            transactions=True, tenant_scoped_reads=True,
            compare_and_swap_updates=True, append_only_audit=True,
            idempotency=True, trusted_actor_context=True,
        )


class _ProjectDocumentAdapter:
    def __init__(self, engine):
        self.engine = engine

    def get(self, session, project_id, company_id):
        return self.engine.get(session, "Project", project_id, company_id)

    def list(self, session, company_id, *, status=None, limit=100, offset=0):
        filters = {"status": status} if status else {}
        return self.engine.list(session, "Project", company_id, filters, limit, offset)

    def insert(self, session, document, *, actor_id):
        return self.engine.insert(session, "Project", document, actor_id)

    def update_if_version(self, session, project_id, company_id, document,
                          *, expected_version, actor_id):
        return self.engine.update_if_version(session, "Project", project_id,
                                             company_id, document, expected_version,
                                             actor_id)


class NativeIntegrationRegistry:
    """Runtime registry populated by the authenticated Velora app bootstrap."""
    def __init__(self):
        self._bridge = None

    def configure(self, bridge: NativeVeloraBridge):
        if not isinstance(bridge, NativeVeloraBridge):
            raise TypeError("Expected a fully validated NativeVeloraBridge.")
        bridge.capabilities().assert_complete()
        self._bridge = bridge

    def get(self) -> NativeVeloraBridge | None:
        return self._bridge

    def readiness(self) -> dict:
        if self._bridge is None:
            return {"configured": False, "production_ready": False,
                    "qualification": "No native Velora bridge was registered by the deployment bootstrap."}
        caps = self._bridge.capabilities()
        return {"configured": True, "production_ready": not caps.missing(),
                "capabilities": caps.__dict__, "missing": caps.missing(),
                "qualification": "Port composition validated; native schema mapping and live staging tests remain deployment responsibilities."}


native_integration_registry = NativeIntegrationRegistry()
