"""Integration health and source freshness projections."""
from __future__ import annotations
from datetime import datetime, timezone


def integration_health(readiness: dict, *, source_status: dict | None = None) -> dict:
    source_status = source_status or {}
    sources = {}
    for name, item in (readiness.get("sources") or {}).items():
        runtime = source_status.get(name, {})
        last_sync = runtime.get("last_success_at")
        error = runtime.get("last_error")
        sources[name] = {
            "configured": bool(item.get("configured")),
            "connected": bool(runtime.get("connected", False)),
            "last_success_at": last_sync,
            "last_error": error,
            "freshness": "unknown" if not last_sync else "reported",
            "write_access": False,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "configured_sources": sum(x["configured"] for x in sources.values()),
        "connected_sources": sum(x["connected"] for x in sources.values()),
        "total_sources": len(sources),
        "production_ready": bool(readiness.get("production_ready")) and all(x["connected"] for x in sources.values()),
        "qualification": "Connectivity and timestamps are deployment-reported; perform tenant-isolation, reconciliation and failure-recovery tests before production approval.",
    }
