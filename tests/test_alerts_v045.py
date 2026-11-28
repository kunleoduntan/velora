import json
from velora.ops_console import configure_alert_policy, evaluate_alerts
from velora.workspace import Workspace


def _ws(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    return ws


def _snapshot():
    return {"health": {"storage": {"free_percent": 4}, "logs": {"recent_error_lines": 40}},
            "databases": {"checked": 2, "healthy": 1},
            "recovery": {"status": "stale", "estimated_rpo_hours": 50}}


def test_alert_policy_default_and_validation(tmp_path):
    ws = _ws(tmp_path)
    policy = configure_alert_policy(ws)
    assert policy["rules"]["disk_free_below_percent"] == 10
    try:
        configure_alert_policy(ws, {"disk_free_below_percent": -1})
    except Exception as exc:
        assert "non-negative" in str(exc)
    else:
        assert False, "negative threshold accepted"


def test_alerts_trigger_and_audit_only_transitions(tmp_path):
    ws = _ws(tmp_path)
    configure_alert_policy(ws)
    first = evaluate_alerts(ws, snapshot=_snapshot())
    assert first["active_count"] == 4
    assert len(first["transitions"]) == 4
    second = evaluate_alerts(ws, snapshot=_snapshot())
    assert second["active_count"] == 4
    assert second["transitions"] == []
    audit = (ws.root / "logs" / "operations-alerts.jsonl").read_text().splitlines()
    assert len(audit) == 4


def test_alert_resolution_is_recorded(tmp_path):
    ws = _ws(tmp_path)
    configure_alert_policy(ws)
    evaluate_alerts(ws, snapshot=_snapshot())
    clear = {"health": {"storage": {"free_percent": 70}, "logs": {"recent_error_lines": 0}},
             "databases": {"checked": 2, "healthy": 2}, "recovery": {"status": "current", "estimated_rpo_hours": 1}}
    result = evaluate_alerts(ws, snapshot=clear)
    assert result["active_count"] == 0
    assert len(result["transitions"]) == 4
    assert all(x["event"] == "resolved" for x in result["transitions"])
