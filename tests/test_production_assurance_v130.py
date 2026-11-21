import json
import os
from datetime import datetime, timezone

from velora.platform_readiness import operational_assurance_report
from velora.workspace import Workspace


def workspace(tmp_path):
    ws = Workspace.create(tmp_path / "workspace")
    return ws


def test_assurance_warns_when_backup_key_and_restore_evidence_missing(tmp_path):
    ws = workspace(tmp_path)
    report = operational_assurance_report(ws, now=datetime(2026, 11, 16, tzinfo=timezone.utc))
    assert report["overall"] == "warning"
    checks = {item["check"]: item for item in report["checks"]}
    assert checks["backup_freshness"]["status"] == "warn"
    assert checks["master_key_protection"]["status"] == "warn"
    assert checks["restore_rehearsal"]["status"] == "warn"
    assert len(report["limitations"]) >= 3


def test_assurance_detects_stale_backup_and_insecure_master_key(tmp_path):
    ws = workspace(tmp_path)
    backup = ws.root / "backups" / "db.dump"
    backup.write_bytes(b"backup placeholder")
    os.utime(backup, (1_700_000_000, 1_700_000_000))
    key_dir = ws.root / "platform"
    key_dir.mkdir()
    key = key_dir / "master.key"
    key.write_text("not-a-real-secret")
    if os.name == "posix":
        key.chmod(0o644)
    report = operational_assurance_report(ws, now=datetime(2026, 11, 16, tzinfo=timezone.utc))
    checks = {item["check"]: item for item in report["checks"]}
    assert checks["backup_freshness"]["status"] == "warn"
    if os.name == "posix":
        assert checks["master_key_protection"]["status"] == "fail"


def test_assurance_accepts_recent_backup_and_verified_restore_evidence(tmp_path):
    from velora.recovery_assurance import record_rehearsal
    ws = workspace(tmp_path)
    backup = ws.root / "backups" / "db.dump"
    backup.write_bytes(b"archive")
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    os.utime(backup, (now.timestamp() - 3600, now.timestamp() - 3600))
    key_dir = ws.root / "platform"
    key_dir.mkdir()
    key = key_dir / "master.key"
    key.write_text("key-material")
    if os.name == "posix":
        key.chmod(0o600)
    record_rehearsal(ws.root, {"status": "passed", "verified": True, "tested_at": now.isoformat(),
                               "recovery_seconds": 20, "restore_duration_seconds": 10})
    report = operational_assurance_report(ws, now=now)
    checks = {item["check"]: item for item in report["checks"]}
    assert checks["backup_freshness"]["status"] == "ok"
    assert checks["restore_rehearsal"]["status"] == "ok"
    if os.name == "posix":
        assert checks["master_key_protection"]["status"] == "ok"
