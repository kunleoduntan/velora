"""Safe adapter for native governance automation dispatch."""
from typing import Callable

ALLOWED_ACTIONS = {"reminder", "escalation", "workflow_route", "notification"}


def execute_governance_actions(actions, *, dispatchers=None, recorder=None, existing_keys=None, dry_run=True):
    """Validate and execute via injected native adapters; never dispatch by itself.

    Dispatcher signature: dispatcher(action) -> result mapping.
    Recorder signature: recorder(action, status, result) -> any.
    """
    dispatchers = dispatchers or {}
    existing = set(existing_keys or [])
    outcomes = []
    for raw in actions or []:
        action = dict(raw or {})
        key = str(action.get("idempotency_key") or "").strip()
        kind = str(action.get("action_type") or "").strip()
        if not key:
            outcomes.append({"status": "rejected", "reason": "missing_idempotency_key"})
            continue
        if key in existing:
            outcomes.append({"status": "duplicate_suppressed", "idempotency_key": key})
            continue
        if kind not in ALLOWED_ACTIONS:
            outcomes.append({"status": "rejected", "idempotency_key": key, "reason": "action_type_not_allowed"})
            continue
        dispatcher = dispatchers.get(kind)
        if not callable(dispatcher):
            outcomes.append({"status": "adapter_unavailable", "idempotency_key": key, "action_type": kind})
            continue
        if dry_run:
            outcomes.append({"status": "validated", "idempotency_key": key, "action_type": kind, "dry_run": True})
            continue
        try:
            result = dispatcher(action)
            status = "dispatched"
            result = result if isinstance(result, dict) else {"result": result}
        except Exception as exc:  # adapter boundary: preserve failure, continue batch
            result = {"error": str(exc), "error_type": type(exc).__name__}
            status = "failed"
        if callable(recorder):
            try:
                recorder(action, status, result)
            except Exception as exc:
                status = "recording_failed"
                result["recording_error"] = str(exc)
        outcomes.append({"status": status, "idempotency_key": key, "action_type": kind, "result": result})
        if status == "dispatched":
            existing.add(key)
    return {"dry_run": bool(dry_run), "total": len(actions or []), "outcomes": outcomes,
            "dispatched": sum(o.get("status") == "dispatched" for o in outcomes),
            "failed": sum(o.get("status") in {"failed", "recording_failed"} for o in outcomes),
            "rejected": sum(o.get("status") == "rejected" for o in outcomes)}
