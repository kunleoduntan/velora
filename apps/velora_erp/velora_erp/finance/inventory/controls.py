"""Stock-control policy from Inventory Settings (reservations, expiry, transit, counting), with safe defaults before it is saved."""
from __future__ import annotations

DEFAULTS = {"reservations_protect_stock": 1, "block_issue_of_expired_batches": 1, "expiry_alert_days": 60, "transit_alert_days": 7,
            "cycle_count_days_a": 30, "cycle_count_days_b": 90, "cycle_count_days_c": 180}


def controls() -> dict:
    out = dict(DEFAULTS)
    try:
        from velora import get_list
        rows = get_list("Inventory Settings", fields=list(DEFAULTS), limit=1, ignore_permissions=True)
    except Exception:  # noqa: BLE001 - settings not created yet
        return out
    if rows:
        out.update({k: v for k, v in rows[0].items() if k in DEFAULTS and v is not None})
    return out
