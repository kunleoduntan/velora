from velora_governance.governance.services.governance_permission_data_gateway import GovernanceDataAdapters, permission_aware_query
from velora_governance.governance.services.governance_transactional_persistence import ReferenceTransactionalRepository, transactional_persist
from velora_governance.governance.services.governance_runtime_dispatch import RuntimeDispatchAdapters, dispatch_workflow, dispatch_notification
from velora_governance.governance.services.governance_ui_integration_manifest import REQUIRED_SURFACES, validate_ui_integration_manifest
from velora_governance.governance.services.governance_integration_qualification_v5_5 import evaluate_v5_5_qualification


def test_permission_gateway_fails_closed_when_permission_adapter_missing():
    result = permission_aware_query(GovernanceDataAdapters(query=lambda *_: [{"id": 1}]),
                                   actor="u", doctype="Board Action")
    assert result["status"] == "adapter_unavailable"
    assert result["data"] == []


def test_permission_gateway_denies_before_query():
    called = []
    adapters = GovernanceDataAdapters(permission_check=lambda *args: False,
                                      query=lambda *args: called.append("query") or [1])
    result = permission_aware_query(adapters, actor="u", doctype="Board Action")
    assert result["status"] == "denied"
    assert called == []


def test_permission_gateway_limits_rows_and_audits():
    audit = []
    adapters = GovernanceDataAdapters(permission_check=lambda *args: True,
                                      query=lambda doctype, request: list(range(20)),
                                      audit=audit.append)
    result = permission_aware_query(adapters, actor="u", doctype="Board Action", limit=7)
    assert result["status"] == "success"
    assert result["count"] == 7
    assert audit[0]["row_count"] == 7


def test_transactional_reference_store_idempotency():
    repo = ReferenceTransactionalRepository()
    one = transactional_persist(repo, {"idempotency_key": "k1", "status": "queued"})
    two = transactional_persist(repo, {"idempotency_key": "k1", "status": "queued"})
    assert one["status"] == two["status"] == "persisted"
    assert one["result"]["created"] is True
    assert two["result"]["created"] is False
    assert one["production_backend"] is False


def test_transactional_persist_requires_key():
    assert transactional_persist(ReferenceTransactionalRepository(), {})["status"] == "rejected"


def test_workflow_dispatch_requires_ids_and_permission():
    adapters = RuntimeDispatchAdapters(permission_check=lambda *args: True,
                                       workflow_dispatch=lambda p: {"ok": True})
    assert dispatch_workflow(adapters, {}, actor="u")["status"] == "rejected"
    payload = {"correlation_id": "c1", "idempotency_key": "i1"}
    assert dispatch_workflow(adapters, payload, actor="u")["status"] == "dispatched"


def test_notification_dispatch_denied():
    adapters = RuntimeDispatchAdapters(permission_check=lambda *args: False,
                                       notification_dispatch=lambda p: True)
    result = dispatch_notification(adapters,
        {"correlation_id": "c1", "idempotency_key": "i1"}, actor="u")
    assert result["status"] == "denied"


def test_ui_manifest_validation():
    valid = {k: dict(v) for k, v in REQUIRED_SURFACES.items()}
    result = validate_ui_integration_manifest(valid)
    assert result["status"] == "valid"
    assert result["ui_installed"] is False
    valid.pop("board_workspace")
    assert validate_ui_integration_manifest(valid)["status"] == "invalid"


def test_v5_5_gate_fails_closed():
    result = evaluate_v5_5_qualification({"native_persistence": True})
    assert result["production_qualified"] is False
    assert len(result["missing_evidence"]) == 9


def test_v5_5_gate_passes_only_complete_evidence():
    from velora_governance.governance.services.governance_integration_qualification_v5_5 import REQUIRED_EVIDENCE
    evidence = {k: True for k in REQUIRED_EVIDENCE}
    result = evaluate_v5_5_qualification(evidence)
    assert result["status"] == "qualified"
    assert result["production_qualified"] is True
