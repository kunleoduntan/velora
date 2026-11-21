import gzip
import json
import sqlite3
from datetime import datetime, timezone, timedelta

from velora.monitoring import monitoring_snapshot, recovery_report, rehearse_database_backup
from velora.workspace import Workspace


def _workspace(tmp_path):
    ws = Workspace.create(tmp_path / "bench")
    site = ws.site_path("demo.local")
    site.mkdir(parents=True)
    db_file = site / "site.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO sample(value) VALUES ('safe')")
    conn.commit(); conn.close()
    (site / "site_config.json").write_text(json.dumps({"db_type": "sqlite", "db_name": "site.db"}))
    return ws, db_file


def test_monitoring_snapshot_probes_site_without_leaking_db_url(tmp_path):
    ws, _ = _workspace(tmp_path)
    report = monitoring_snapshot(ws)
    assert report["databases"]["checked"] == 1
    assert report["databases"]["healthy"] == 1
    assert report["status"] in {"ok", "warning"}
    assert "sqlite:///" not in json.dumps(report)


def test_sqlite_backup_rehearsal_is_read_only_and_integrity_checked(tmp_path):
    ws, db_file = _workspace(tmp_path)
    backup = ws.root / "sample.db.gz"
    with db_file.open("rb") as source, gzip.open(backup, "wb") as target:
        target.write(source.read())
    result = rehearse_database_backup(backup)
    assert result["status"] == "passed"
    assert result["engine"] == "sqlite"
    assert result["integrity_check"] == "ok"
    assert result["table_count"] == 1
    # The source database remains unchanged.
    conn = sqlite3.connect(db_file)
    assert conn.execute("SELECT value FROM sample").fetchone()[0] == "safe"
    conn.close()


def test_postgres_dump_is_explicitly_preflight_only(tmp_path):
    backup = tmp_path / "pg.sql.gz"
    with gzip.open(backup, "wb") as f:
        f.write(b"-- PostgreSQL database dump\nCREATE TABLE public.example(id integer);\n")
    result = rehearse_database_backup(backup)
    assert result["status"] == "preflight_only"
    assert "not a restore test" in result["note"]


def test_recovery_report_calculates_rpo_from_successful_audit(tmp_path):
    ws, _ = _workspace(tmp_path)
    now = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)
    audit = ws.root / "logs" / "backup-audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps({"timestamp": (now - timedelta(hours=3)).isoformat(), "status": "success"}) + "\n"
                    + json.dumps({"timestamp": now.isoformat(), "status": "partial"}) + "\n")
    report = recovery_report(ws, now=now)
    assert report["status"] == "current"
    assert report["estimated_rpo_hours"] == 3.0
    assert report["latest_run_status"] == "partial"
    assert report["successful_runs"] == 1


def test_recovery_report_unknown_without_audit(tmp_path):
    ws, _ = _workspace(tmp_path)
    report = recovery_report(ws)
    assert report["status"] == "unknown"
    assert report["estimated_rpo_hours"] is None
