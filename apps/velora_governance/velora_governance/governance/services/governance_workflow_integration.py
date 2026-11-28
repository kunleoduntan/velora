"""Governance workflow integration using injected native workflow adapters."""
ALLOWED_DECISIONS = {"approve", "reject", "request_changes", "delegate"}

def route_governance_approval(request, *, routing_config=None, workflow_adapter=None):
    request = dict(request or {})
    cfg = dict(routing_config or {})
    if not request.get("document_type") or not request.get("document_name"):
        return {"status": "rejected", "reason": "document_reference_required"}
    route_key = request.get("route_key") or cfg.get("default_route")
    routes = cfg.get("routes", {})
    route = routes.get(route_key)
    if not route:
        return {"status": "rejected", "reason": "configured_route_not_found", "route_key": route_key}
    if not callable(workflow_adapter):
        return {"status": "adapter_unavailable", "route_key": route_key}
    payload = {"document_type": request["document_type"], "document_name": request["document_name"],
               "route_key": route_key, "route": route, "context": request.get("context", {})}
    try:
        result = workflow_adapter(payload)
    except Exception as exc:
        return {"status": "failed", "route_key": route_key, "error": str(exc), "error_type": type(exc).__name__}
    return {"status": "routed", "route_key": route_key, "result": result}

def record_approval_decision(request, *, decision, actor, workflow_adapter=None, context=None):
    if decision not in ALLOWED_DECISIONS:
        return {"status": "rejected", "reason": "decision_not_allowed"}
    if not actor:
        return {"status": "rejected", "reason": "actor_required"}
    if not callable(workflow_adapter):
        return {"status": "adapter_unavailable"}
    payload = {"request": dict(request or {}), "decision": decision, "actor": actor, "context": context or {}}
    try:
        result = workflow_adapter(payload)
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "error_type": type(exc).__name__}
    return {"status": "decision_recorded", "decision": decision, "actor": actor, "result": result}
