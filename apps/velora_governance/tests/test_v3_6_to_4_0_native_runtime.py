import pytest
from velora_governance.governance.services.governance_native_integration import (
    NativeIntegrationAdapters, qualify_native_integrations, persist_automation_action,
    execute_native_workflow, deliver_native_notification, run_native_scheduled_job,
)
from velora_governance.governance.services.governance_production_gate import REQUIRED_GATES, build_production_gate_report

class Backend:
    def __init__(self): self.records = {}
    def insert_if_absent(self, record):
        return self.records.setdefault(record["idempotency_key"], record)

def test_native_integration_qualification_reports_missing_adapters():
    result = qualify_native_integrations(NativeIntegrationAdapters())
    assert result["status"] == "not_ready"
    assert "persistence" in result["missing"]

def test_persistence_requires_idempotency_and_suppresses_duplicates():
    backend = Backend()
    adapters = NativeIntegrationAdapters(persistence=backend)
    assert persist_automation_action(adapters, {})["status"] == "rejected"
    action = {"idempotency_key": "abc", "kind": "reminder"}
    first = persist_automation_action(adapters, action)
    second = persist_automation_action(adapters, action)
    assert first["status"] == second["status"] == "persisted"
    assert len(backend.records) == 1

def test_workflow_and_notification_are_permission_gated():
    denied = NativeIntegrationAdapters(permission_check=lambda *args: False,
                                      workflow=lambda payload: "ok", notification=lambda payload: "sent")
    assert execute_native_workflow(denied, {}, actor="x")["status"] == "denied"
    assert deliver_native_notification(denied, {}, actor="x")["status"] == "denied"
    allowed = NativeIntegrationAdapters(permission_check=lambda *args: True,
                                       workflow=lambda payload: "ok", notification=lambda payload: "sent")
    assert execute_native_workflow(allowed, {}, actor="x")["status"] == "executed"
    assert deliver_native_notification(allowed, {}, actor="x")["status"] == "delivered"

def test_scheduler_adapter_status_and_error_isolation():
    missing = run_native_scheduled_job(NativeIntegrationAdapters(), {})
    assert missing["status"] == "scheduler_adapter_unavailable"
    broken = NativeIntegrationAdapters(scheduler=lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    assert run_native_scheduled_job(broken, {})["status"] == "failed"

def test_production_gate_requires_every_gate():
    report = build_production_gate_report({}, release_version="4.0.0")
    assert report["status"] == "not_qualified"
    assert set(report["blockers"]) == set(REQUIRED_GATES)
    passing = build_production_gate_report({g: "passed" for g in REQUIRED_GATES}, release_version="4.0.0")
    assert passing["production_qualified"] is True
