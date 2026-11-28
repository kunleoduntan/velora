"""Audited project commands and the exceptions shared by the document ports.

Persistence itself is always Velora's document engine (see ``host_adapter``);
this module holds only the command service that runs against any repository
implementing the same small contract.
"""
from __future__ import annotations

from copy import deepcopy

from .lifecycle import validate_project, transition_project


class PersistenceError(RuntimeError):
    """Base class for persistence failures."""


class TenantScopeError(PermissionError):
    """Raised when a record is accessed outside its scope."""


class VersionConflict(PersistenceError):
    """Raised when the stored version differs from the version supplied."""


class IdempotencyConflict(PersistenceError):
    """Raised when an idempotency key is reused for a different request."""


class ProjectCommandService:
    """Application service; actor and company are supplied by trusted host context."""
    IMMUTABLE = {"project_code", "created_by", "creation", "name", "version", "status"}

    def __init__(self, repository):
        self.repository = repository

    def create(self, company: str, actor_id: str, data: dict):
        payload = deepcopy(data or {})
        validate_project(payload)
        payload.setdefault("status", "Draft")
        payload.setdefault("progress_percent", 0)
        payload.setdefault("project_health", "Not Started")
        return self.repository.insert(payload, actor_id=actor_id, scope=company)

    def read(self, company: str, project_id: str):
        result = self.repository.get(project_id, company)
        if result is None:
            raise KeyError(project_id)
        return result

    def update(self, company: str, actor_id: str, project_id: str, changes: dict, expected_version: int):
        current = self.read(company, project_id)
        payload = deepcopy(current)
        for key, value in (changes or {}).items():
            if key in self.IMMUTABLE:
                raise ValueError(f"{key} must be changed through its controlled operation or is immutable.")
            payload[key] = value
        validate_project(payload)
        return self.repository.update(project_id, company, payload, expected_version=expected_version, actor_id=actor_id)

    def transition(self, company: str, actor_id: str, project_id: str, target_status: str, evidence: dict, expected_version: int):
        current = self.read(company, project_id)
        if current["version"] != expected_version:
            raise VersionConflict("Project version conflict; reload before transition.")
        result = transition_project(current.get("status", "Draft"), target_status, evidence or {})
        updated = deepcopy(current)
        updated["status"] = target_status
        saved = self.repository.update(project_id, company, updated, expected_version=expected_version, actor_id=actor_id, action="project.lifecycle.transition")
        return {"project": saved, "transition": result}
