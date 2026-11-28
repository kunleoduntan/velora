"""Operational monitoring and non-destructive recovery assurance for Velora workspaces."""
from __future__ import annotations

import gzip
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

from .workspace import Workspace, WorkspaceError


def _probe_database(name: str, url: str) -> dict:
    """Probe connectivity without returning the URL or credentials."""
    engine = None
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args={"timeout": 3} if url.startswith("sqlite:") else {})
        with engine.connect() as conn:
            value = conn.execute(text("SELECT 1")).scalar_one()
        return {"name": name, "status": "ok", "probe": int(value)}
    except Exception as exc:
        return {"name": name, "status": "fail", "error": f"{type(exc).__name__}: database probe failed"}
    finally:
        if engine is not None:
            engine.dispose()


def monitoring_snapshot(ws: Workspace) -> dict:
    """Collect bounded-time site/control-plane/tenant database probes and host signals."""
    from .operations import health_snapshot
    from .site import db_url_from_config, read_site_config

    base = health_snapshot(ws)
    probes: list[dict] = []
    for site_name in ws.sites():
        try:
            site_dir = ws.site_path(site_name)
            cfg = read_site_config(site_dir)
            probes.append(_probe_database(f"site:{site_name}", db_url_from_config(cfg, site_dir)))
        except Exception as exc:
            probes.append({"name": f"site:{site_name}", "status": "fail", "error": f"{type(exc).__name__}: site configuration unavailable"})

    if (ws.root / "platform" / "control_plane.json").exists():
        try:
            from .controlplane import ControlPlane
            plane = ControlPlane.open(ws)
            cfg = plane.cfg
            if cfg.get("db_type", "sqlite") == "sqlite":
                db_path = plane.platform_dir / cfg.get("db_name", "control.db")
                url = f"sqlite:///{db_path.resolve()}"
            else:
                from .site import db_url_from_config
                url = db_url_from_config(cfg, plane.platform_dir)
            probes.append(_probe_database("control_plane", url))
            for company in plane.registry.list_companies():
                if company.get("status", "active") != "active":
                    continue
                try:
                    probes.append(_probe_database(f"company:{company['id']}", plane.router.db_url(company)))
                except Exception:
                    probes.append({"name": f"company:{company.get('id', 'unknown')}", "status": "fail", "error": "tenant database configuration unavailable"})
        except Exception as exc:
            probes.append({"name": "control_plane", "status": "fail", "error": f"{type(exc).__name__}: control-plane probe unavailable"})

    failures = [p["name"] for p in probes if p["status"] != "ok"]
    base["databases"] = {"checked": len(probes), "healthy": len(probes) - len(failures), "failures": failures, "probes": probes}
    if failures or base["status"] == "fail":
        base["status"] = "fail"
    base["generated_at"] = datetime.now(timezone.utc).isoformat()
    return base


def recovery_report(ws: Workspace, *, now: datetime | None = None, warning_after_hours: int = 26) -> dict:
    """Summarize backup evidence from the append-only scheduler audit log and backup files."""
    if warning_after_hours < 1:
        raise WorkspaceError("warning_after_hours must be at least 1")
    now = now or datetime.now(timezone.utc)
    audit = ws.root / "logs" / "backup-audit.jsonl"
    events = []
    if audit.exists():
        for line_no, line in enumerate(audit.read_text(errors="replace").splitlines(), 1):
            try:
                item = json.loads(line)
                if isinstance(item, dict) and item.get("timestamp"):
                    events.append(item)
            except json.JSONDecodeError:
                continue
    successful = [e for e in events if e.get("status") == "success"]
    latest = max(successful, key=lambda e: e.get("timestamp", ""), default=None)
    latest_dt = None
    if latest:
        try:
            latest_dt = datetime.fromisoformat(latest["timestamp"])
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            latest_dt = None
    age_hours = round((now - latest_dt).total_seconds() / 3600, 2) if latest_dt else None
    backup_files = []
    for folder in (ws.root / "backups", ws.root / "sites", ws.root / "platform"):
        if folder.exists():
            for path in folder.rglob("*"):
                if path.is_file() and (path.name.endswith(".gz") or path.name.endswith(".vbackup")):
                    try:
                        backup_files.append({"file": str(path.relative_to(ws.root)), "bytes": path.stat().st_size,
                                             "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
                    except OSError:
                        continue
    if latest_dt is None:
        status = "unknown"
    elif age_hours > warning_after_hours:
        status = "stale"
    else:
        status = "current"
    return {"generated_at": now.isoformat(), "status": status, "warning_after_hours": warning_after_hours,
            "latest_successful_run": latest.get("timestamp") if latest else None, "estimated_rpo_hours": age_hours,
            "successful_runs": len(successful), "recorded_runs": len(events),
            "latest_run_status": events[-1].get("status") if events else None,
            "backup_file_count": len(backup_files), "backup_files": sorted(backup_files, key=lambda x: x["modified_at"], reverse=True),
            "limitations": ["RPO is estimated from the scheduler audit log, not proof of recoverability.",
                            "A restore rehearsal must be run separately for each database backup.",
                            "PostgreSQL dump files receive format preflight only; no disposable PostgreSQL restore is performed."]}


def rehearse_database_backup(path: str | Path) -> dict:
    """Non-destructively rehearse a compressed database backup in an isolated temporary location.

    SQLite backups are decompressed and opened read-only for PRAGMA integrity_check.
    PostgreSQL plain SQL dumps receive a structural preflight only; no live DB is modified.
    """
    backup = Path(path)
    if not backup.is_file():
        raise WorkspaceError(f"Backup file does not exist: {backup}")
    try:
        with gzip.open(backup, "rb") as stream:
            prefix = stream.read(4096)
            if not prefix:
                raise WorkspaceError("Database backup is empty")
            if prefix.startswith(b"SQLite format 3\x00"):
                with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
                    tmp.write(prefix)
                    while chunk := stream.read(1024 * 1024):
                        tmp.write(chunk)
                    tmp.flush()
                    uri = f"file:{tmp.name}?mode=ro"
                    conn = sqlite3.connect(uri, uri=True)
                    try:
                        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                    finally:
                        conn.close()
                    if result != "ok":
                        raise WorkspaceError(f"SQLite restore rehearsal failed integrity_check: {result}")
                    return {"status": "passed", "engine": "sqlite", "file": backup.name,
                            "integrity_check": result, "table_count": tables,
                            "method": "decompressed into a temporary file and opened read-only"}
            rest = stream.read(1024 * 1024)
            sample = prefix + rest
            if b"PostgreSQL database dump" in sample or b"CREATE TABLE" in sample or b"SET statement_timeout" in sample:
                return {"status": "preflight_only", "engine": "postgresql", "file": backup.name,
                        "method": "gzip decompression and SQL dump signature preflight",
                        "note": "This is not a restore test. Use an isolated disposable PostgreSQL database and psql with ON_ERROR_STOP for a true restore rehearsal."}
            raise WorkspaceError("Unrecognized compressed database backup format")
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise WorkspaceError(f"Database backup rehearsal failed: {exc}") from exc
