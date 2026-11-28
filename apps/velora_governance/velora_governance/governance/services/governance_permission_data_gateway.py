"""Permission-first data gateway contracts for Velora Governance.

Host Velora APIs must provide the permission checker and query adapter. This module
never performs direct database access and fails closed when adapters are absent.
"""
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class GovernanceDataAdapters:
    permission_check: Callable | None = None
    query: Callable | None = None
    audit: Callable | None = None


def permission_aware_query(adapters: GovernanceDataAdapters, *, actor, doctype, filters=None,
                          fields=None, limit=100, scope=None):
    if not callable(adapters.permission_check):
        return {"status": "adapter_unavailable", "adapter": "permission_check", "data": []}
    request = {"doctype": doctype, "filters": dict(filters or {}), "fields": list(fields or []),
              "limit": max(1, min(int(limit or 100), 500)), "scope": dict(scope or {})}
    try:
        allowed = adapters.permission_check(actor, "read", doctype, request["scope"])
    except Exception as exc:
        return {"status": "permission_check_failed", "error_type": type(exc).__name__, "data": []}
    if not allowed:
        return {"status": "denied", "data": []}
    if not callable(adapters.query):
        return {"status": "adapter_unavailable", "adapter": "query", "data": []}
    try:
        rows = adapters.query(doctype, request)
        rows = list(rows or [])[:request["limit"]]
        if callable(adapters.audit):
            adapters.audit({"event": "governance_permission_aware_query", "actor": actor,
                           "doctype": doctype, "row_count": len(rows)})
        return {"status": "success", "data": rows, "count": len(rows), "request": request}
    except Exception as exc:
        return {"status": "query_failed", "error_type": type(exc).__name__, "data": []}
