from pathlib import Path
from types import SimpleNamespace

import pytest

from velora.upgrade import plan as upgrade_plan


def test_plan_fingerprint_ignores_creation_timestamp(monkeypatch, tmp_path):
    monkeypatch.setattr(upgrade_plan.UpgradeEngine, "plan", lambda self: [{"id": "site-a", "schema": [], "patches": [], "warnings": []}])
    monkeypatch.setattr(upgrade_plan, "code_version", lambda: "0.56.0")
    ws = SimpleNamespace(root=tmp_path)
    first = upgrade_plan.build_plan(ws)
    second = upgrade_plan.build_plan(ws)
    assert first["created_at"] and second["created_at"]
    assert first["fingerprint"] == second["fingerprint"]


def test_plan_file_detects_tampering_and_target_drift(monkeypatch, tmp_path):
    monkeypatch.setattr(upgrade_plan.UpgradeEngine, "plan", lambda self: [{"id": "site-a", "schema": [], "patches": [], "warnings": []}])
    monkeypatch.setattr(upgrade_plan, "code_version", lambda: "0.56.0")
    ws = SimpleNamespace(root=tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(__import__("json").dumps(upgrade_plan.build_plan(ws)))
    assert upgrade_plan.verify_plan_file(ws, path)["verified"] is True
    payload = __import__("json").loads(path.read_text())
    payload["targets"][0]["schema"].append("ALTER TABLE")
    path.write_text(__import__("json").dumps(payload))
    with pytest.raises(ValueError, match="fingerprint"):
        upgrade_plan.verify_plan_file(ws, path)


def test_plan_file_rejects_changed_live_plan(monkeypatch, tmp_path):
    rows = [{"id": "site-a", "schema": [], "patches": [], "warnings": []}]
    monkeypatch.setattr(upgrade_plan.UpgradeEngine, "plan", lambda self: rows)
    monkeypatch.setattr(upgrade_plan, "code_version", lambda: "0.56.0")
    ws = SimpleNamespace(root=tmp_path)
    path = tmp_path / "plan.json"
    path.write_text(__import__("json").dumps(upgrade_plan.build_plan(ws)))
    rows[0]["schema"].append("ALTER TABLE")
    with pytest.raises(ValueError, match="live migration plan has changed"):
        upgrade_plan.verify_plan_file(ws, path)
