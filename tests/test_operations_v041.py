import json
from pathlib import Path
import pytest
from velora.workspace import Workspace, WorkspaceError
from velora.operations import health_snapshot, create_encrypted_backup, verify_encrypted_backup, prune_backups


def workspace(tmp_path):
    ws = Workspace.create(tmp_path / "site")
    (ws.sites_dir / "demo.local").mkdir(parents=True)
    (ws.sites_dir / "demo.local" / "site_config.json").write_text(json.dumps({"db_type": "sqlite", "db_name": "demo.db", "db_password": "secret"}))
    ws.apps_file.write_text("\n")
    (ws.root / "config" / "settings.json").write_text('{"safe": true}')
    return ws


def disk(monkeypatch, total, free):
    """Pretend the disk has this much free space, so the result never depends on the machine the tests run on."""
    import collections
    import velora.operations as ops
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(ops.shutil, "disk_usage", lambda _p: usage(total, total - free, free))


def test_health_snapshot_has_no_secret_values(tmp_path, monkeypatch):
    disk(monkeypatch, 1000, 500)
    ws = workspace(tmp_path)
    result = health_snapshot(ws)
    assert result["sites"]["names"] == ["demo.local"]
    assert result["status"] == "ok"
    assert "secret" not in json.dumps(result)


def test_health_status_follows_free_disk_space_and_missing_apps(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    for total, free, status in ((1000, 500, "ok"), (1000, 100, "ok"), (1000, 99, "warning"), (1000, 0, "warning"), (0, 0, "warning")):
        disk(monkeypatch, total, free)
        assert health_snapshot(ws)["status"] == status, (total, free)                                  # exactly 10% free is still fine; a zero-size disk must not crash
    disk(monkeypatch, 1000, 500)
    ws.apps_file.write_text("ghost\n")
    assert health_snapshot(ws)["status"] == "fail" and health_snapshot(ws)["applications"]["missing_directories"] == ["ghost"]


def test_encrypted_backup_roundtrip_and_wrong_password(tmp_path):
    ws = workspace(tmp_path)
    backup = create_encrypted_backup(ws, "correct horse battery")
    assert backup.exists()
    result = verify_encrypted_backup(backup, "correct horse battery")
    assert result["valid"] is True
    with pytest.raises(WorkspaceError, match="incorrect"):
        verify_encrypted_backup(backup, "wrong password here")


def test_backup_rejects_weak_password(tmp_path):
    ws = workspace(tmp_path)
    with pytest.raises(WorkspaceError, match="12 characters"):
        create_encrypted_backup(ws, "weak")


def test_retention_keeps_newest(tmp_path):
    ws = workspace(tmp_path)
    folder = ws.root / "backups"; folder.mkdir(exist_ok=True)
    files = []
    for i in range(4):
        p = folder / f"{i}.vbackup"; p.write_text(str(i)); files.append(p)
    import os, time
    for i, p in enumerate(files): os.utime(p, (100+i, 100+i))
    removed = prune_backups(ws, keep=2)
    assert len(removed) == 2
    assert {p.name for p in folder.glob("*.vbackup")} == {"2.vbackup", "3.vbackup"}


def test_retention_must_be_positive(tmp_path):
    with pytest.raises(WorkspaceError): prune_backups(workspace(tmp_path), keep=0)
