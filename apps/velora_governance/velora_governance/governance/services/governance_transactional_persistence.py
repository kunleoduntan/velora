"""Transactional/idempotent persistence adapter contract.

Production backends must implement insert_if_absent atomically within the host
transaction boundary. This reference adapter is intentionally test-only.
"""
from threading import RLock

class ReferenceTransactionalRepository:
    test_only = True
    def __init__(self):
        self._records = {}
        self._lock = RLock()
    def insert_if_absent(self, record):
        key = str(record.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("idempotency_key_required")
        with self._lock:
            if key in self._records:
                return {"created": False, "record": self._records[key]}
            saved = dict(record)
            self._records[key] = saved
            return {"created": True, "record": saved}
    def get_by_key(self, key):
        with self._lock:
            return self._records.get(key)


def transactional_persist(repository, record, *, audit=None):
    record = dict(record or {})
    key = str(record.get("idempotency_key") or "").strip()
    if not key:
        return {"status": "rejected", "reason": "idempotency_key_required"}
    if repository is None or not callable(getattr(repository, "insert_if_absent", None)):
        return {"status": "adapter_unavailable"}
    if getattr(repository, "test_only", False):
        # Reference/test repository can never qualify production persistence.
        production_backend = False
    else:
        production_backend = bool(getattr(repository, "transactional", False) and
                                 getattr(repository, "atomic_idempotency", False))
    try:
        result = repository.insert_if_absent(record)
        if callable(audit):
            audit({"event": "governance_transactional_persist", "idempotency_key": key,
                   "created": bool((result or {}).get("created"))})
        return {"status": "persisted", "production_backend": production_backend,
                "result": result}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}
