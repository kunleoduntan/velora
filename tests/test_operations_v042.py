import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from velora.workspace import Workspace, WorkspaceError
from velora.operations import (
    configure_backup_policy, read_backup_policy, backup_status,
    run_scheduled_backups, _verify_database_backup,
)


def make_workspace(tmp_path):
    ws = Workspace.create(tmp_path / "ws")
    site = ws.sites_dir / "demo.local"
    (site / "private").mkdir(parents=True)
    db_file = site / "demo.db"
    conn = sqlite3.connect(db_file)
    conn.execute("create table sample (id integer primary key, value text)")
    conn.execute("insert into sample(value) values ('ok')")
    conn.commit(); conn.close()
    (site / "site_config.json").write_text(json.dumps({"db_type": "sqlite", "db_name": "demo.db"}))
    return ws


def test_policy_validation_and_status(tmp_path):
    ws = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError):
        configure_backup_policy(ws, every_hours=0)
    policy = configure_backup_policy(ws, every_hours=6, keep=3, workspace_snapshot=False)
    assert policy["every_hours"] == 6
    assert read_backup_policy(ws)["keep"] == 3
    assert backup_status(ws)["configured"] is True


def test_scheduled_database_backup_verify_and_not_due(tmp_path):
    ws = make_workspace(tmp_path)
    configure_backup_policy(ws, every_hours=24, keep=3, workspace_snapshot=False, verify=True)
    moment = datetime(2026, 11, 11, 5, tzinfo=timezone.utc)
    result = run_scheduled_backups(ws, now_at=moment)
    assert result["status"] == "success"
    assert len(result["created"]) == 1
    assert result["verified"][0]["valid"] is True
    second = run_scheduled_backups(ws, now_at=moment + timedelta(hours=1))
    assert second["status"] == "not_due"
    assert (ws.root / "logs" / "backup-audit.jsonl").exists()


def test_scheduled_workspace_snapshot_requires_password(tmp_path):
    ws = make_workspace(tmp_path)
    configure_backup_policy(ws, workspace_snapshot=True)
    result = run_scheduled_backups(ws, now_at=datetime(2026, 11, 11, tzinfo=timezone.utc))
    assert result["status"] == "partial"
    assert "VELORA_BACKUP_PASSWORD" in result["errors"][0]["error"]
    # A partial run does not advance last_success, so it can be retried immediately.
    retry = run_scheduled_backups(ws, password="correct horse battery", now_at=datetime(2026, 11, 11, 1, tzinfo=timezone.utc))
    assert retry["status"] == "success"
    assert any(x["scope"] == "workspace" for x in retry["created"])


def test_database_backup_verification_rejects_corrupt_file(tmp_path):
    bad = tmp_path / "broken.db.gz"
    bad.write_bytes(b"not gzip")
    with pytest.raises(WorkspaceError, match="verification failed"):
        _verify_database_backup(bad)


def test_missing_policy_is_actionable(tmp_path):
    ws = make_workspace(tmp_path)
    with pytest.raises(WorkspaceError, match="ops configure"):
        read_backup_policy(ws)
