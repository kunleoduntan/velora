"""Safe adapter contract for the existing Velora SLA capability.

This module intentionally does not implement SLA targets, calendars, timers, or breach rules.
The SLA-owning app remains the system of record. Governance consumes normalized facts.
"""
ALLOWED_STATUS = {"On Track", "Due Soon", "Breached", "Paused", "Met", "Unknown"}


def normalize_sla_facts(payload=None):
    """Normalize SLA facts supplied by the existing SLA app; preserve source ownership."""
    p = dict(payload or {})
    status = str(p.get("sla_status") or "Unknown").strip()
    if status not in ALLOWED_STATUS:
        status = "Unknown"
    return {
        "sla_provider": str(p.get("sla_provider") or "").strip() or None,
        "sla_reference": str(p.get("sla_reference") or "").strip() or None,
        "sla_status": status,
        "target_at": p.get("target_at"),
        "breached_at": p.get("breached_at"),
        "elapsed_seconds": _nonnegative_int(p.get("elapsed_seconds")),
        "remaining_seconds": _nonnegative_int(p.get("remaining_seconds")),
        "source_updated_at": p.get("source_updated_at"),
        "integration_state": "normalized_external_fact" if p.get("sla_provider") else "provider_not_identified",
    }


def _nonnegative_int(value):
    if value in (None, ""): return None
    try: n = int(value)
    except (TypeError, ValueError): return None
    return max(0, n)
