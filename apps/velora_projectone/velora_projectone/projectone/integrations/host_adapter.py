"""Velora host repository adapter built only on explicit injected ports."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..services.persistence import VersionConflict
from .host_contracts import HostProjectBridge, AuthenticatedActor


class VeloraProjectRepository:
    """Repository-compatible adapter; host APIs are injected, never inferred.

    The bridge implementation is responsible for mapping these operations to
    Velora's native document engine and transaction/audit services.
    """

    def __init__(self, bridge: HostProjectBridge, *, require_production_capabilities: bool = True):
        self.bridge = bridge
        self.require_production_capabilities = require_production_capabilities
        self._validate_bridge()

    def _validate_bridge(self):
        required = ("uow", "projects", "audit", "idempotency", "capabilities")
        absent = [name for name in required if not hasattr(self.bridge, name)]
        if absent:
            raise TypeError("Host bridge is missing required ports: " + ", ".join(absent))
        capabilities = self.bridge.capabilities()
        if self.require_production_capabilities:
            capabilities.assert_complete()

    @staticmethod
    def _actor(actor_id: str, company_id: str):
        # The application boundary must pass values from AuthenticatedActor.
        if not actor_id or not company_id:
            raise PermissionError("Trusted actor and company context are required.")

    def get(self, project_id: str, company: str):
        if not company:
            raise ValueError("Company scope is required.")
        with self.bridge.uow.transaction() as session:
            row = self.bridge.projects.get(session, project_id, company)
        return deepcopy(row) if row else None

    def list(self, company: str, *, status: str | None = None, limit: int = 100, offset: int = 0):
        if not company:
            raise ValueError("Company scope is required.")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be zero or greater.")
        with self.bridge.uow.transaction() as session:
            rows = self.bridge.projects.list(session, company, status=status, limit=limit, offset=offset)
        return deepcopy(rows)

    def insert(self, document: dict, *, actor_id: str, scope: str, conn=None):
        row = deepcopy(document)
        company = scope
        self._actor(actor_id, company)
        row.pop("version", None)
        with self.bridge.uow.transaction() as session:
            saved = self.bridge.projects.insert(session, row, actor_id=actor_id)
            self.bridge.audit.append(session, company_id=company, project_id=saved["name"],
                                      actor_id=actor_id, action="project.created",
                                      before=None, after=saved)
        return deepcopy(saved)

    def update(self, project_id: str, company: str, document: dict, *, expected_version: int,
               actor_id: str, action: str = "project.updated", conn=None):
        self._actor(actor_id, company)
        with self.bridge.uow.transaction() as session:
            before = self.bridge.projects.get(session, project_id, company)
            if before is None:
                raise KeyError(project_id)
            if before.get("version") != expected_version:
                raise VersionConflict("Project was modified by another user; reload before saving.")
            after = deepcopy(document)
            after.pop("company", None)
            after.pop("version", None)
            after["name"] = project_id
            saved = self.bridge.projects.update_if_version(
                session, project_id, company, after,
                expected_version=expected_version, actor_id=actor_id,
            )
            self.bridge.audit.append(session, company_id=company, project_id=project_id,
                                      actor_id=actor_id, action=action,
                                      before=before, after=saved)
        return deepcopy(saved)

    def audit_events(self, project_id: str, company: str, *, limit: int = 100):
        if not company:
            raise ValueError("Company scope is required.")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500.")
        with self.bridge.uow.transaction() as session:
            return deepcopy(self.bridge.audit.list_for_project(
                session, project_id, company, limit=limit
            ))

    def execute_idempotent(self, company: str, key: str, request_hash: str, operation):
        if not company or not key or not request_hash:
            raise ValueError("company, idempotency key and request hash are required.")
        with self.bridge.uow.transaction() as session:
            return deepcopy(self.bridge.idempotency.execute(
                session, company, key, request_hash, operation
            ))


def authenticated_actor_from_host(host_user: Any) -> AuthenticatedActor:
    """Normalize a trusted host principal; reject body-shaped/untrusted objects."""
    if isinstance(host_user, AuthenticatedActor):
        return host_user
    if host_user is None or getattr(host_user, "is_authenticated", False) is not True:
        raise PermissionError("An authenticated Velora host principal is required.")
    actor_id = getattr(host_user, "user_id", None)
    company_id = getattr(host_user, "company_id", None)
    roles = getattr(host_user, "roles", ())
    permissions = getattr(host_user, "permissions", ())
    if isinstance(roles, str) or isinstance(permissions, str):
        raise TypeError("Host roles and permissions must be collections, not strings.")
    return AuthenticatedActor(str(actor_id or ""), str(company_id or ""),
                              frozenset(roles or ()), frozenset(permissions or ()))
