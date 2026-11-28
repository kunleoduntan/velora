"""Explicit host-framework ports for production Velora integration.

No Velora internals are guessed here. A deployment adapter must implement these
ports against the installed Velora document engine, authorization context,
transaction manager, audit service and idempotency store.
"""
from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthenticatedActor:
    """Trusted identity supplied by the host request/session middleware."""
    actor_id: str
    company_id: str
    roles: frozenset[str]
    permissions: frozenset[str] = frozenset()

    def __post_init__(self):
        if not self.actor_id or not self.company_id:
            raise ValueError("Authenticated actor and company are required.")


@dataclass(frozen=True)
class HostCapabilities:
    """Capabilities required before enabling persistent ProjectOne commands."""
    transactions: bool
    tenant_scoped_reads: bool
    compare_and_swap_updates: bool
    append_only_audit: bool
    idempotency: bool
    trusted_actor_context: bool

    def missing(self) -> list[str]:
        return [name for name, enabled in self.__dict__.items() if not enabled]

    def assert_complete(self):
        missing = self.missing()
        if missing:
            raise RuntimeError("ProjectOne host adapter is not production-ready; missing: " + ", ".join(missing))


@runtime_checkable
class UnitOfWorkPort(Protocol):
    def transaction(self) -> AbstractContextManager[Any]: ...


@runtime_checkable
class ProjectDocumentPort(Protocol):
    """Methods must enforce company scope in the database query itself."""
    def get(self, session: Any, project_id: str, company_id: str) -> dict | None: ...
    def list(self, session: Any, company_id: str, *, status: str | None, limit: int, offset: int) -> list[dict]: ...
    def insert(self, session: Any, document: dict, *, actor_id: str) -> dict: ...
    def update_if_version(self, session: Any, project_id: str, company_id: str,
                          document: dict, *, expected_version: int, actor_id: str) -> dict: ...


@runtime_checkable
class AuditPort(Protocol):
    """append() must be append-only and participate in the active transaction."""
    def append(self, session: Any, *, company_id: str, project_id: str, actor_id: str,
               action: str, before: dict | None, after: dict | None) -> None: ...
    def list_for_project(self, session: Any, project_id: str, company_id: str,
                         *, limit: int) -> list[dict]: ...


@runtime_checkable
class IdempotencyPort(Protocol):
    """Atomic reserve/replay operation, backed by a unique company/key constraint."""
    def execute(self, session: Any, company_id: str, key: str, request_hash: str,
                operation) -> dict: ...


@runtime_checkable
class HostProjectBridge(Protocol):
    uow: UnitOfWorkPort
    projects: ProjectDocumentPort
    audit: AuditPort
    idempotency: IdempotencyPort

    def capabilities(self) -> HostCapabilities: ...
