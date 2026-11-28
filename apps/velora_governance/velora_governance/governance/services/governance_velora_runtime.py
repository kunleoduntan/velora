"""Concrete Governance persistence adapter for the Velora Document API.

This adapter uses the framework APIs already used by the app: get_list, get_doc,
new_doc and Document.insert/save. It is intended to be called from trusted server
code after the caller's native permission check. The unique idempotency field on
Governance Automation Execution is the database-level duplicate guard.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


DOCTYPE = "Governance Automation Execution"


def _json(value):
    return json.dumps(value if value is not None else {}, sort_keys=True, default=str)


def _decode(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {"raw": str(value)}


class VeloraGovernanceExecutionRepository:
    """Persistent repository backed by Velora's native document functions."""
    transactional = False  # Native transaction semantics must be qualified in-host.
    atomic_idempotency = True  # Backed by the DocType unique field; concurrency still needs host testing.
    native_document_api = True
    runtime_qualified = False

    def __init__(self, api=None):
        # Injection is primarily for tests. Production resolves the host APIs lazily.
        self.api = api

    def _api(self):
        if self.api is not None:
            return self.api
        from velora import get_doc, get_list, new_doc
        return {"get_doc": get_doc, "get_list": get_list, "new_doc": new_doc}

    def _find(self, key):
        api = self._api()
        rows = api["get_list"](DOCTYPE, filters={"idempotency_key": key}, fields=["name"], limit=1, ignore_permissions=True)
        return rows[0]["name"] if rows else None

    def insert_if_absent(self, record):
        record = dict(record or {})
        key = str(record.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("idempotency_key_required")
        existing = self._find(key)
        if existing:
            return {"created": False, "record": self.get_by_idempotency_key(key)}
        action = dict(record.get("action") or {})
        api = self._api()
        doc = api["new_doc"](DOCTYPE)
        doc.idempotency_key = key
        doc.correlation_id = str(action.get("correlation_id") or record.get("correlation_id") or "")
        doc.action_type = str(action.get("action_type") or action.get("type") or "Governance Action")
        doc.action_payload = _json(action)
        doc.execution_status = record.get("status", "Queued")
        doc.attempts = int(record.get("attempts", 0) or 0)
        doc.actor = str(record.get("actor") or "")
        doc.last_result = _json(record.get("result") or {})
        doc.insert(ignore_permissions=True)
        return {"created": True, "record": self._serialize(doc)}

    def get_by_idempotency_key(self, key):
        name = self._find(key)
        if not name:
            return None
        doc = self._api()["get_doc"](DOCTYPE, name, ignore_permissions=True)
        return self._serialize(doc)

    def update_status(self, key, status, result=None, *, error=None, attempts=None, next_retry_at=None):
        name = self._find(key)
        if not name:
            raise KeyError(key)
        doc = self._api()["get_doc"](DOCTYPE, name, ignore_permissions=True)
        doc.execution_status = status
        if attempts is not None:
            doc.attempts = int(attempts)
        doc.last_result = _json(result or {})
        doc.last_error = str(error or "")
        if status in ("Running", "Completed"):
            doc.next_retry_at = None
        elif next_retry_at is not None:
            doc.next_retry_at = next_retry_at
        now = datetime.now(timezone.utc).isoformat()
        if status == "Running" and not getattr(doc, "started_at", None):
            doc.started_at = now
        if status == "Completed":
            doc.completed_at = now
        doc.save(ignore_permissions=True)
        return self._serialize(doc)

    def list_records(self, status=None, *, limit=100, offset=0):
        limit = max(1, min(int(limit or 100), 500))
        if isinstance(status, (list, tuple, set)):
            filters = {"execution_status": ["in", list(status)]}
        else:
            filters = {"execution_status": status} if status else None
        rows = self._api()["get_list"](DOCTYPE, filters=filters, fields=["name"], limit=limit, offset=max(0, int(offset or 0)), ignore_permissions=True)
        return [self._serialize(self._api()["get_doc"](DOCTYPE, row["name"], ignore_permissions=True)) for row in rows]

    def list_idempotency_keys(self, *, limit=500):
        rows = self._api()["get_list"](DOCTYPE, fields=["idempotency_key"], limit=max(1, min(int(limit), 500)), ignore_permissions=True)
        return [row.get("idempotency_key") for row in rows if row.get("idempotency_key")]

    @staticmethod
    def _serialize(doc):
        return {
            "name": getattr(doc, "name", None),
            "idempotency_key": getattr(doc, "idempotency_key", None),
            "correlation_id": getattr(doc, "correlation_id", None),
            "action_type": getattr(doc, "action_type", None),
            "action": _decode(getattr(doc, "action_payload", None)),
            "status": getattr(doc, "execution_status", None),
            "attempts": getattr(doc, "attempts", 0),
            "actor": getattr(doc, "actor", None),
            "result": _decode(getattr(doc, "last_result", None)),
            "error": getattr(doc, "last_error", None),
            "next_retry_at": getattr(doc, "next_retry_at", None),
            "started_at": getattr(doc, "started_at", None),
            "completed_at": getattr(doc, "completed_at", None),
        }


def persist_native_automation_action(action, *, actor=None, repository=None):
    action = dict(action or {})
    key = str(action.get("idempotency_key") or "").strip()
    if not key:
        return {"status": "rejected", "reason": "idempotency_key_required"}
    repo = repository or VeloraGovernanceExecutionRepository()
    try:
        result = repo.insert_if_absent({"idempotency_key": key, "action": action,
                                      "status": "Queued", "attempts": 0,
                                      "actor": actor, "result": {}})
        return {"status": "persisted", "created": bool(result.get("created")),
                "record": result.get("record"), "native_document_api": True, "runtime_qualified": False}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__,
                "message": str(exc)}
