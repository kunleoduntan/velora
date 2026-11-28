from velora_governance.governance.services.governance_action_store import GovernanceActionStore
from velora_governance.governance.services.governance_workflow_integration import route_governance_approval, record_approval_decision
from velora_governance.governance.services.governance_notification_centre import plan_notifications, dispatch_notifications
from velora_governance.governance.services.board_portal_workspace import build_board_workspace
from velora_governance.governance.services.governance_qualification import build_qualification_report


def test_action_store_idempotency_and_retry():
    store = GovernanceActionStore()
    action = {"idempotency_key": "abc", "action_type": "reminder"}
    first = store.record(action, "failed", {"error": "temporary"})
    second = store.record(action, "failed", {"error": "retry"})
    assert first is second
    assert store.get("abc")["attempts"] == 2
    store.mark_retry("abc")
    assert store.retry_candidates(max_attempts=4)[0]["attempts"] == 3
    assert "abc" in store.existing_keys()


def test_workflow_routing_config_and_adapter():
    cfg = {"default_route": "board", "routes": {"board": {"approvers": ["chair"]}}}
    result = route_governance_approval({"document_type": "Resolution", "document_name": "RES-1"},
        routing_config=cfg, workflow_adapter=lambda payload: {"workflow_id": "WF-1"})
    assert result["status"] == "routed"
    assert result["route_key"] == "board"
    assert route_governance_approval({}, routing_config=cfg)["status"] == "rejected"


def test_approval_decision_validates_actor_and_decision():
    assert record_approval_decision({}, decision="approve", actor="user-1",
        workflow_adapter=lambda p: "ok")["status"] == "decision_recorded"
    assert record_approval_decision({}, decision="anything", actor="user-1")["status"] == "rejected"


def test_notification_planning_preferences_and_delivery_idempotency():
    events = [{"event_id": "evt-1", "event_type": "action_due", "recipient_ids": ["u1", "u2"], "payload": {"x": 1}}]
    prefs = {"u1": {"channels": ["in_app", "email"]}, "u2": {"disabled": True}}
    templates = {"action_due": {"template_key": "due", "channels": ["in_app", "email"]}}
    plans = plan_notifications(events, preferences=prefs, templates=templates)
    assert len(plans) == 2
    delivered = dispatch_notifications(plans, dispatchers={"in_app": lambda p: "sent", "email": lambda p: "sent"}, dry_run=False)
    assert delivered["delivered"] == 2
    dup = dispatch_notifications(plans, dispatchers={"in_app": lambda p: "sent", "email": lambda p: "sent"}, existing_keys={p["idempotency_key"] for p in plans}, dry_run=False)
    assert all(o["status"] == "duplicate_suppressed" for o in dup["outcomes"])


def test_board_workspace_scopes_and_document_allowlist():
    result = build_board_workspace(audience_id="committee-1", audience_type="committee",
        meetings=[{"id": "m1", "audience_id": "committee-1"}, {"id": "m2", "audience_id": "committee-2"}],
        agenda_items=[{"meeting_id": "m1", "title": "A"}, {"meeting_id": "m2", "title": "B"}],
        actions=[{"audience_id": "committee-1", "status": "open"}, {"audience_id": "committee-2", "status": "open"}],
        documents=[{"id": "doc1"}, {"id": "doc2"}], allowed_document_ids=["doc2"])
    assert len(result["meetings"]) == 1
    assert len(result["agenda_items"]) == 1
    assert len(result["actions"]) == 1
    assert [d["id"] for d in result["documents"]] == ["doc2"]


def test_qualification_report_blocks_until_all_evidence():
    report = build_qualification_report(evidence={"installation": {"status": "passed", "evidence": "test"}})
    assert report["qualification_status"] == "not_qualified"
    assert report["production_qualified"] is False
    full = {area: {"status": "passed"} for area in [c["area"] for c in report["checks"]]}
    assert build_qualification_report(evidence=full)["qualification_status"] == "ready_for_signoff"
