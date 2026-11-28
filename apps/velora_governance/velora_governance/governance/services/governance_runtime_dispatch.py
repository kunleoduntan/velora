"""Guarded workflow and notification runtime dispatch.
All dispatch requires authorization, correlation and idempotency identifiers.
"""
from dataclasses import dataclass
from typing import Callable

@dataclass
class RuntimeDispatchAdapters:
    permission_check: Callable | None = None
    workflow_dispatch: Callable | None = None
    notification_dispatch: Callable | None = None
    audit: Callable | None = None


def _dispatch(kind, adapters, payload, actor):
    payload = dict(payload or {})
    correlation_id = str(payload.get("correlation_id") or "").strip()
    idempotency_key = str(payload.get("idempotency_key") or "").strip()
    if not correlation_id or not idempotency_key:
        return {"status": "rejected", "reason": "correlation_and_idempotency_required"}
    if not callable(adapters.permission_check):
        return {"status": "permission_adapter_unavailable"}
    try:
        if not adapters.permission_check(actor, f"governance_{kind}_dispatch", payload):
            return {"status": "denied"}
    except Exception as exc:
        return {"status": "permission_check_failed", "error_type": type(exc).__name__}
    dispatch = adapters.workflow_dispatch if kind == "workflow" else adapters.notification_dispatch
    if not callable(dispatch):
        return {"status": f"{kind}_adapter_unavailable"}
    try:
        result = dispatch(payload)
        if callable(adapters.audit):
            adapters.audit({"event": f"governance_{kind}_dispatch", "actor": actor,
                           "correlation_id": correlation_id, "idempotency_key": idempotency_key,
                           "outcome": "success"})
        return {"status": "dispatched", "result": result, "correlation_id": correlation_id}
    except Exception as exc:
        if callable(adapters.audit):
            adapters.audit({"event": f"governance_{kind}_dispatch", "actor": actor,
                           "correlation_id": correlation_id, "idempotency_key": idempotency_key,
                           "outcome": "failure", "error_type": type(exc).__name__})
        return {"status": "failed", "error_type": type(exc).__name__, "correlation_id": correlation_id}


def dispatch_workflow(adapters, payload, *, actor=None):
    return _dispatch("workflow", adapters, payload, actor)

def dispatch_notification(adapters, payload, *, actor=None):
    return _dispatch("notification", adapters, payload, actor)
