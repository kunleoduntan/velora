"""Repository contract and reference store for governance automation executions.

Native production persistence must implement the same contract using the Velora
Document API/transaction layer. The in-memory implementation is for tests and
local qualification only.
"""
from threading import RLock

class GovernanceActionStore:
    def __init__(self, backend=None):
        self.backend = backend
        self._records = {}
        self._lock = RLock()

    def get(self, key):
        if self.backend:
            return self.backend.get_by_idempotency_key(key)
        with self._lock:
            return self._records.get(key)

    def record(self, action, status, result=None):
        key = str((action or {}).get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("idempotency_key is required")
        record = {"idempotency_key": key, "action": dict(action), "status": status,
                  "result": result or {}, "attempts": 1}
        if self.backend:
            return self.backend.insert_if_absent(record)
        with self._lock:
            existing = self._records.get(key)
            if existing:
                if status in {"failed", "retry_pending"}:
                    existing["attempts"] += 1
                    existing["status"] = status
                    existing["result"] = result or {}
                return existing
            self._records[key] = record
            return record

    def mark_retry(self, key, result=None):
        if self.backend:
            return self.backend.update_status(key, "retry_pending", result or {})
        with self._lock:
            rec = self._records.get(key)
            if not rec:
                raise KeyError(key)
            rec["attempts"] += 1
            rec["status"] = "retry_pending"
            rec["result"] = result or {}
            return rec

    def list_records(self, status=None):
        if self.backend:
            return self.backend.list_records(status=status)
        with self._lock:
            records = list(self._records.values())
            return [r for r in records if status is None or r["status"] == status]

    def existing_keys(self):
        if self.backend:
            return set(self.backend.list_idempotency_keys())
        with self._lock:
            return set(self._records)

    def retry_candidates(self, max_attempts=3):
        return [r for r in self.list_records() if r["status"] in {"failed", "retry_pending"} and r["attempts"] < max_attempts]
