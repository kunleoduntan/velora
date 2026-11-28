import json
from velora.ops_console import render_dashboard, write_dashboard, operations_snapshot
from velora.workspace import Workspace


def _ws(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    ws.apps_file.write_text("demo\n")
    (ws.root / "apps" / "demo").mkdir(parents=True)
    return ws


def test_dashboard_html_contains_snapshot_and_escapes_dynamic_values(tmp_path):
    snap = {"workspace": "<script>alert(1)</script>", "generated_at": "now", "overall": "ok",
            "health": {"sites": {"count": 1}, "applications": {"registered": ["demo"]},
                       "storage": {"free_percent": 50}, "logs": {"recent_error_lines": 0}},
            "databases": {"checked": 1, "healthy": 1, "probes": [{"name": "site:demo", "status": "ok"}]},
            "recovery": {"status": "current", "estimated_rpo_hours": 2}}
    page = render_dashboard(snap)
    assert "Velora Operations" in page and "site:demo" in page
    assert "&lt;script&gt;" in page and "<script>alert" not in page


def test_dashboard_writes_report_under_reports(tmp_path):
    ws = _ws(tmp_path)
    target = write_dashboard(ws)
    assert target.exists() and "Velora Operations" in target.read_text()


def test_operations_snapshot_has_expected_sections(tmp_path):
    ws = _ws(tmp_path)
    snap = operations_snapshot(ws)
    assert {"health", "databases", "recovery", "overall"} <= snap.keys()
