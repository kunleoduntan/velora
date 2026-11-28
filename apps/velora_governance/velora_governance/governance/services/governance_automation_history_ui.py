"""v4.7 automation execution history view and safe retry preview."""

TERMINAL = {"completed", "success", "dispatched"}


def build_automation_history_view(runs, *, page=1, page_size=25, filters=None):
    filters = filters or {}
    rows = list(runs or [])
    if filters.get("status"):
        rows = [r for r in rows if str(r.get("status", "")).lower() == str(filters["status"]).lower()]
    if filters.get("action_type"):
        rows = [r for r in rows if r.get("action_type") == filters["action_type"]]
    page = max(1, int(page)); page_size = max(1, min(100, int(page_size)))
    total = len(rows); start = (page - 1) * page_size
    return {"rows": rows[start:start + page_size], "page": page, "page_size": page_size,
            "total": total, "pages": (total + page_size - 1) // page_size,
            "retry_execution_enabled": False, "version": "4.7.0"}


def preview_retry(run, *, max_attempts=3, permission_checked=False, idempotency_verified=False):
    run = run or {}
    attempts = int(run.get("attempts") or 0)
    status = str(run.get("status") or "").lower()
    reasons = []
    if status not in {"failed", "error"}: reasons.append("run_not_failed")
    if not run.get("retryable", False): reasons.append("not_marked_retryable")
    if attempts >= max_attempts: reasons.append("attempt_limit_reached")
    if not permission_checked: reasons.append("permission_check_required")
    if not idempotency_verified or not run.get("idempotency_key"): reasons.append("idempotency_verification_required")
    return {"eligible": not reasons, "reasons": reasons, "execution_enabled": False,
            "source_run": run.get("name"), "attempts": attempts, "max_attempts": max_attempts,
            "version": "4.7.0"}
