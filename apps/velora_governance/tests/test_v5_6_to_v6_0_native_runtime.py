import json
from types import SimpleNamespace

from velora_governance.governance.services.governance_velora_runtime import (
    VeloraGovernanceExecutionRepository,
    persist_native_automation_action,
)


class FakeDoc:
    def __init__(self, store, name=None):
        self._store = store
        self.name = name

    def insert(self, ignore_permissions=False):
        if not ignore_permissions:
            raise AssertionError("trusted runtime insert should use controlled permissions")
        if any(d.idempotency_key == self.idempotency_key for d in self._store.values()):
            raise ValueError("unique idempotency key conflict")
        self.name = f"GAE-{len(self._store)+1:08d}"
        self._store[self.name] = self
        return self

    def save(self, ignore_permissions=False):
        if not ignore_permissions:
            raise AssertionError("trusted runtime save should use controlled permissions")
        self._store[self.name] = self
        return self


class FakeAPI:
    def __init__(self):
        self.store = {}

    def new_doc(self, doctype):
        assert doctype == "Governance Automation Execution"
        return FakeDoc(self.store)

    def get_list(self, doctype, filters=None, fields=None, limit=100, offset=0, ignore_permissions=False):
        assert doctype == "Governance Automation Execution"
        assert ignore_permissions
        rows = list(self.store.values())
        if filters:
            rows = [d for d in rows if all(getattr(d, k) == v for k, v in filters.items())]
        return [{f: getattr(d, f, None) for f in fields} for d in rows[offset:offset+limit]]

    def get_doc(self, doctype, name, ignore_permissions=False):
        assert doctype == "Governance Automation Execution"
        assert ignore_permissions
        return self.store[name]


def test_native_document_repository_persists_action_and_idempotently_returns_existing():
    api = FakeAPI()
    repo = VeloraGovernanceExecutionRepository(api={
        "get_list": api.get_list, "get_doc": api.get_doc, "new_doc": api.new_doc,
    })
    action = {"idempotency_key": "daily-reminder:2026-11-26", "action_type": "Reminder",
              "correlation_id": "corr-001", "recipient": "user@example.test"}
    first = repo.insert_if_absent({"idempotency_key": action["idempotency_key"], "action": action,
                                   "status": "Queued", "actor": "scheduler"})
    second = repo.insert_if_absent({"idempotency_key": action["idempotency_key"], "action": action,
                                    "status": "Queued", "actor": "scheduler"})
    assert first["created"] is True
    assert second["created"] is False
    assert len(api.store) == 1
    assert second["record"]["action"]["correlation_id"] == "corr-001"


def test_native_action_persist_requires_idempotency_key():
    result = persist_native_automation_action({}, repository=FakeAPI())
    assert result == {"status": "rejected", "reason": "idempotency_key_required"}


def test_native_repository_updates_status_and_records_attempts():
    api = FakeAPI()
    repo = VeloraGovernanceExecutionRepository(api={
        "get_list": api.get_list, "get_doc": api.get_doc, "new_doc": api.new_doc,
    })
    repo.insert_if_absent({"idempotency_key": "k-2", "action": {"type": "test"}, "status": "Queued"})
    updated = repo.update_status("k-2", "Failed", {"code": "transient"}, error="temporary failure", attempts=1)
    assert updated["status"] == "Failed"
    assert updated["attempts"] == 1
    assert updated["error"] == "temporary failure"


def test_native_repository_list_is_bounded_and_filters_status():
    api = FakeAPI()
    repo = VeloraGovernanceExecutionRepository(api={
        "get_list": api.get_list, "get_doc": api.get_doc, "new_doc": api.new_doc,
    })
    for i in range(3):
        repo.insert_if_absent({"idempotency_key": f"k-{i}", "action": {"type": "test"}, "status": "Queued"})
    assert len(repo.list_records(status="Queued", limit=9999)) == 3
    assert len(repo.list_records(status="Completed")) == 0
