"""Project aggregate commands and persistence port.

Persistence is deliberately injected: the host framework owns transactions,
identity, permissions, naming and durable storage.
"""
from copy import deepcopy
from datetime import date
from threading import RLock
from uuid import uuid4
from .lifecycle import validate_project, transition_project

IMMUTABLE_FIELDS = {"project_code", "created_by", "creation"}

class ProjectRepository:
    """Minimal repository contract for a host-backed Project DocType adapter."""
    def get(self, project_id): raise NotImplementedError
    def insert(self, document): raise NotImplementedError
    def update(self, project_id, document, expected_version): raise NotImplementedError

class InMemoryProjectRepository(ProjectRepository):
    """Thread-safe reference adapter for tests and local domain development only."""
    def __init__(self): self._rows, self._lock = {}, RLock()
    def get(self, project_id):
        with self._lock:
            row = self._rows.get(project_id)
            return deepcopy(row) if row else None
    def insert(self, document):
        with self._lock:
            row = deepcopy(document); key = row.setdefault("name", str(uuid4()))
            if key in self._rows: raise ValueError("Project already exists.")
            row["version"] = 1; self._rows[key] = row
            return deepcopy(row)
    def update(self, project_id, document, expected_version):
        with self._lock:
            current = self._rows.get(project_id)
            if not current: raise KeyError(project_id)
            if current["version"] != expected_version: raise RuntimeError("Project was changed by another user; reload before saving.")
            row = deepcopy(document); row["name"] = project_id; row["version"] = expected_version + 1
            self._rows[project_id] = row
            return deepcopy(row)

def create_project(repository, data):
    payload = deepcopy(data or {})
    validate_project(payload)
    payload.setdefault("status", "Draft")
    payload.setdefault("progress_percent", 0)
    payload.setdefault("project_health", "Not Started")
    payload.setdefault("currency", None)
    payload["created_on"] = date.today().isoformat()
    return repository.insert(payload)

def update_project(repository, project_id, changes, expected_version):
    current = repository.get(project_id)
    if not current: raise KeyError(project_id)
    if not isinstance(expected_version, int) or expected_version < 1: raise ValueError("A valid expected_version is required.")
    payload = deepcopy(current)
    for key, value in (changes or {}).items():
        if key in IMMUTABLE_FIELDS: raise ValueError(f"{key} is immutable after project creation.")
        if key in {"status", "version", "name", "created_on"}: raise ValueError(f"{key} must be changed through its controlled lifecycle operation.")
        payload[key] = value
    validate_project(payload)
    return repository.update(project_id, payload, expected_version)

def change_project_status(repository, project_id, target_status, evidence=None, expected_version=None):
    current = repository.get(project_id)
    if not current: raise KeyError(project_id)
    if expected_version != current["version"]: raise RuntimeError("Project version conflict; reload before changing lifecycle state.")
    transition = transition_project(current.get("status", "Draft"), target_status, evidence)
    updated = deepcopy(current); updated["status"] = target_status
    if target_status == "Active" and not updated.get("actual_start_date"):
        updated["actual_start_date"] = date.today().isoformat()
    if target_status in {"Completed", "Closed"} and not updated.get("actual_end_date"):
        updated["actual_end_date"] = date.today().isoformat()
    saved = repository.update(project_id, updated, expected_version)
    return {"project": saved, "transition": transition}
