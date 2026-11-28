"""Native integration orchestration contracts for Velora Governance.

Adapters must be supplied by the host Velora runtime. This module never performs
unauthorized persistence, workflow, notification, scheduler, or permission work.
"""
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class NativeIntegrationAdapters:
    persistence: Any = None
    workflow: Callable | None = None
    notification: Callable | None = None
    permission_check: Callable | None = None
    scheduler: Callable | None = None
    audit: Callable | None = None

    def diagnostics(self):
        return {
            "persistence": bool(self.persistence),
            "workflow": callable(self.workflow),
            "notification": callable(self.notification),
            "permission_check": callable(self.permission_check),
            "scheduler": callable(self.scheduler),
            "audit": callable(self.audit),
        }


def qualify_native_integrations(adapters: NativeIntegrationAdapters, *, required=None):
    required = list(required or ["persistence", "workflow", "notification", "permission_check", "scheduler", "audit"])
    diagnostics = adapters.diagnostics()
    missing = [name for name in required if not diagnostics.get(name, False)]
    return {"status": "ready" if not missing else "not_ready", "required": required,
            "diagnostics": diagnostics, "missing": missing,
            "production_qualified": not missing}


def persist_automation_action(adapters: NativeIntegrationAdapters, action, *, actor=None):
    """Persist an action via host adapter with a required idempotency key."""
    action = dict(action or {})
    key = str(action.get("idempotency_key") or "").strip()
    if not key:
        return {"status": "rejected", "reason": "idempotency_key_required"}
    backend = adapters.persistence
    if backend is None or not callable(getattr(backend, "insert_if_absent", None)):
        return {"status": "adapter_unavailable"}
    record = {"idempotency_key": key, "action": action, "status": "queued", "actor": actor,
              "attempts": 0, "result": {}}
    try:
        saved = backend.insert_if_absent(record)
        if callable(adapters.audit):
            adapters.audit({"event": "governance_action_persisted", "key": key, "actor": actor})
        return {"status": "persisted", "record": saved}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}


def execute_native_workflow(adapters: NativeIntegrationAdapters, payload, *, actor=None):
    if not callable(adapters.permission_check):
        return {"status": "permission_adapter_unavailable"}
    try:
        allowed = adapters.permission_check(actor, "governance_workflow_execute", payload)
    except Exception as exc:
        return {"status": "permission_check_failed", "error_type": type(exc).__name__}
    if not allowed:
        return {"status": "denied"}
    if not callable(adapters.workflow):
        return {"status": "workflow_adapter_unavailable"}
    try:
        result = adapters.workflow(dict(payload or {}))
        if callable(adapters.audit):
            adapters.audit({"event": "governance_workflow_executed", "actor": actor})
        return {"status": "executed", "result": result}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}


def deliver_native_notification(adapters: NativeIntegrationAdapters, payload, *, actor=None):
    if not callable(adapters.permission_check):
        return {"status": "permission_adapter_unavailable"}
    try:
        if not adapters.permission_check(actor, "governance_notification_send", payload):
            return {"status": "denied"}
    except Exception as exc:
        return {"status": "permission_check_failed", "error_type": type(exc).__name__}
    if not callable(adapters.notification):
        return {"status": "notification_adapter_unavailable"}
    try:
        result = adapters.notification(dict(payload or {}))
        if callable(adapters.audit):
            adapters.audit({"event": "governance_notification_delivered", "actor": actor})
        return {"status": "delivered", "result": result}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}


def run_native_scheduled_job(adapters: NativeIntegrationAdapters, job_payload, *, actor="scheduler"):
    if not callable(adapters.scheduler):
        return {"status": "scheduler_adapter_unavailable"}
    try:
        result = adapters.scheduler(dict(job_payload or {}))
        if callable(adapters.audit):
            adapters.audit({"event": "governance_scheduled_job_run", "actor": actor})
        return {"status": "completed", "result": result}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)}
