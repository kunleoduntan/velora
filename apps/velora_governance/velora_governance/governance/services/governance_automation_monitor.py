"""Automation operations monitoring, retry selection, and history summaries."""
from collections import Counter


RETRYABLE_STATUSES = {"failed", "recording_failed", "delivery_failed", "timeout"}


def build_automation_monitor(records=None, *, max_retry_attempts=3):
    records = list(records or [])
    by_status = Counter(str(row.get("status", "unknown")).lower() for row in records)
    retry_candidates = []
    for row in records:
        status = str(row.get("status", "")).lower()
        attempts = int(row.get("attempts", row.get("retry_count", 0)) or 0)
        if status in RETRYABLE_STATUSES and row.get("retryable", True) and attempts < max_retry_attempts:
            retry_candidates.append({"id": row.get("name", row.get("id")), "idempotency_key": row.get("idempotency_key"),
                                    "attempts": attempts, "status": status, "reason": row.get("error") or status})
    return {
        "total": len(records), "status_counts": dict(by_status),
        "success_count": by_status.get("dispatched", 0) + by_status.get("delivered", 0) + by_status.get("completed", 0),
        "failure_count": sum(by_status.get(s, 0) for s in RETRYABLE_STATUSES),
        "retry_candidates": retry_candidates,
        "retry_candidate_count": len(retry_candidates),
        "max_retry_attempts": int(max_retry_attempts),
        "retry_execution_enabled": False,
        "note": "This monitor identifies retry candidates only; execution must use native adapters and authorization.",
    }
