"""Production-readiness inventory and integrity manifests for a Velora workspace.

This module is deliberately read-only except for writing an explicitly requested manifest.
It never opens tenant databases, changes configuration, or includes credentials in output.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .workspace import Workspace, WorkspaceError

_EXCLUDED = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}
_SECRET_NAMES = {"site_config.json", "control_plane.json", "master.key", ".env"}


def _json_file(path: Path) -> tuple[dict | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None, "must contain a JSON object"
        return value, None
    except FileNotFoundError:
        return None, "file is missing"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"cannot be read: {exc}"


def _check(name: str, status: str, detail: str, remediation: str = "") -> dict[str, str]:
    return {"check": name, "status": status, "detail": detail, "remediation": remediation}


def readiness_report(ws: Workspace, *, min_free_bytes: int = 512 * 1024 * 1024) -> dict[str, Any]:
    """Inspect workspace structure/configuration without connecting to or modifying databases."""
    checks: list[dict[str, str]] = []
    common_path = ws.common_config_file
    common, error = _json_file(common_path)
    checks.append(_check("common_config", "fail" if error else "ok", error or "valid JSON object",
                         "Repair config/common.json" if error else ""))

    registered = ws.apps()
    missing = [a for a in registered if not (ws.apps_dir / a).is_dir()]
    unregistered = sorted(p.name for p in ws.apps_dir.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name not in registered) if ws.apps_dir.exists() else []
    checks.append(_check("app_registry", "fail" if missing else "warn" if unregistered else "ok",
                         f"{len(registered)} registered; {len(missing)} missing; {len(unregistered)} unregistered",
                         ("Missing app source: " + ", ".join(missing)) if missing else ("Review unregistered app folders: " + ", ".join(unregistered)) if unregistered else ""))

    sites = ws.sites()
    if not sites:
        checks.append(_check("sites", "warn", "No sites are provisioned", "Create a site with `velora new-site`"))
    else:
        checks.append(_check("sites", "ok", f"{len(sites)} site(s) discovered"))
    for name in sites:
        path = ws.site_path(name)
        cfg_path = path / "site_config.json"
        cfg, err = _json_file(cfg_path)
        if err:
            checks.append(_check(f"site:{name}:config", "fail", err, f"Repair {cfg_path}"))
            continue
        db_type = cfg.get("db_type", "sqlite")
        valid = db_type in ("sqlite", "postgres")
        if db_type == "postgres":
            valid = valid and all(cfg.get(k) for k in ("db_name", "db_user", "db_password"))
        elif db_type == "sqlite":
            valid = valid and bool(cfg.get("db_name", "site.db"))
        checks.append(_check(f"site:{name}:database_config", "ok" if valid else "fail",
                             f"database type: {db_type}" if valid else "database configuration is incomplete or unsupported",
                             "Check db_type and required database connection fields" if not valid else ""))
        if os.name == "posix":
            mode = stat.S_IMODE(cfg_path.stat().st_mode)
            secure = mode & 0o077 == 0
            checks.append(_check(f"site:{name}:config_permissions", "ok" if secure else "warn", f"mode {mode:04o}",
                                 f"Run chmod 600 {cfg_path}" if not secure else ""))

    if common is not None:
        update = common.get("update", {})
        if update and not isinstance(update, dict):
            checks.append(_check("update_config", "fail", "update must be a JSON object", "Correct config/common.json"))
        elif isinstance(update, dict):
            restart = update.get("restart_command")
            safe_shape = restart is None or (isinstance(restart, list) and bool(restart) and all(isinstance(x, str) for x in restart))
            checks.append(_check("restart_command", "ok" if safe_shape else "warn",
                                 "argument-list command configured" if isinstance(restart, list) and safe_shape else "not configured" if restart is None else "command should be an argument list, not a shell string",
                                 "Configure update.restart_command as an array, e.g. [\"systemctl\", \"restart\", \"velora\"]" if not safe_shape else ""))

    try:
        free = shutil.disk_usage(ws.root).free
        checks.append(_check("disk_space", "ok" if free >= min_free_bytes else "warn", f"{free / (1024**3):.2f} GiB free",
                             "Free disk space before upgrades and backups" if free < min_free_bytes else ""))
    except OSError as exc:
        checks.append(_check("disk_space", "warn", str(exc)))

    for dirname in ("backups", "logs", "config"):
        folder = ws.root / dirname
        exists = folder.is_dir()
        writable = exists and os.access(folder, os.W_OK)
        checks.append(_check(f"workspace:{dirname}", "ok" if writable else "warn", "directory writable" if writable else "directory missing or not writable",
                             f"Create and grant write access to {folder}" if not writable else ""))

    statuses = [c["status"] for c in checks]
    overall = "fail" if "fail" in statuses else "warning" if "warn" in statuses else "ready"
    return {"framework_version": __version__, "workspace": str(ws.root), "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall": overall, "summary": {s: statuses.count(s) for s in ("ok", "warn", "fail")}, "checks": checks}


def build_deployment_manifest(ws: Workspace) -> dict[str, Any]:
    """Create a credential-free SHA-256 inventory of framework and app source files."""
    ws.activate()
    files: list[dict[str, Any]] = []
    app_versions: dict[str, str] = {}
    from .apps import app_version
    for app in sorted(ws.apps()):
        root = ws.app_path(app)
        if not root.is_dir() or root.is_symlink() or not root.resolve().is_relative_to(ws.apps_dir.resolve()):
            raise WorkspaceError(f"Cannot create manifest: app source {app!r} is missing or outside the workspace")
        app_versions[app] = app_version(app)
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if any(part in _EXCLUDED for part in rel.parts) or path.name in _SECRET_NAMES or path.suffix in {".pyc", ".pyo", ".db", ".sqlite"}:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append({"path": f"apps/{app}/{rel.as_posix()}", "sha256": digest, "size": path.stat().st_size})
    return {"format": "velora-deployment-manifest", "format_version": 1, "framework_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(), "apps": app_versions, "files": files}


def write_deployment_manifest(ws: Workspace, destination: str | Path | None = None) -> Path:
    """Write a deployment manifest atomically with restrictive permissions."""
    target = Path(destination) if destination else ws.root / "config" / "deployment-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(build_deployment_manifest(ws), indent=2, sort_keys=True) + "\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    if os.name == "posix":
        os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def verify_deployment_manifest(ws: Workspace, manifest_path: str | Path) -> dict[str, Any]:
    """Verify every recorded source file; report missing or changed files without modifying anything."""
    manifest, error = _json_file(Path(manifest_path))
    if error:
        raise WorkspaceError(f"Invalid deployment manifest: {error}")
    if manifest.get("format") != "velora-deployment-manifest" or manifest.get("format_version") != 1:
        raise WorkspaceError("Unsupported deployment manifest format")
    checked, missing, changed = 0, [], []
    for item in manifest.get("files", []):
        rel = Path(item.get("path", ""))
        if rel.is_absolute() or ".." in rel.parts:
            raise WorkspaceError(f"Unsafe manifest path: {rel}")
        path = ws.root / rel
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(ws.root.resolve()):
                raise WorkspaceError(f"Manifest path escapes workspace or follows a symlink: {rel}")
        except OSError:
            missing.append(str(rel)); continue
        if not path.is_file():
            missing.append(str(rel)); continue
        checked += 1
        if path.stat().st_size != item.get("size") or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            changed.append(str(rel))
    return {"valid": not missing and not changed, "checked": checked, "missing": missing, "changed": changed,
            "framework_version": manifest.get("framework_version"), "apps": manifest.get("apps", {})}


def operational_assurance_report(ws: Workspace, *, backup_max_age_hours: int = 24,
                                 now: datetime | None = None) -> dict[str, Any]:
    """Assess backup freshness, key-file protection and restore evidence without touching tenant data.

    This is an operational evidence check, not a live database or security penetration test.
    """
    now = now or datetime.now(timezone.utc)
    checks: list[dict[str, str]] = []
    backup_dir = ws.root / "backups"
    backups = [p for p in backup_dir.iterdir() if p.is_file() and not p.is_symlink()] if backup_dir.is_dir() else []
    if not backups:
        checks.append(_check("backup_freshness", "warn", "No backup files found",
                             "Create a database backup and configure a recurring backup schedule"))
    else:
        latest = max(backups, key=lambda p: p.stat().st_mtime)
        age = max(0.0, (now.timestamp() - latest.stat().st_mtime) / 3600)
        fresh = age <= backup_max_age_hours
        checks.append(_check("backup_freshness", "ok" if fresh else "warn",
                             f"Latest backup is {age:.1f} hours old ({len(backups)} file(s) found)",
                             "Create a fresh backup and investigate the backup schedule" if not fresh else ""))

    key_candidates = [ws.root / "platform" / "master.key", ws.root / "config" / "master.key"]
    key_path = next((p for p in key_candidates if p.is_file() and not p.is_symlink()), None)
    if key_path is None:
        checks.append(_check("master_key_protection", "warn", "No local master.key file found",
                             "If encryption keys are managed externally, document that control; otherwise provision and protect the master key"))
    elif os.name == "posix":
        mode = stat.S_IMODE(key_path.stat().st_mode)
        secure = mode & 0o077 == 0
        checks.append(_check("master_key_protection", "ok" if secure else "fail", f"mode {mode:04o}",
                             f"Run chmod 600 {key_path}" if not secure else ""))
    else:
        checks.append(_check("master_key_protection", "warn", "Master key file exists; ACLs were not inspected",
                             "Verify that only the service identity and designated administrators can read the key"))

    try:
        from .recovery_assurance import recovery_assurance_report
        recovery = recovery_assurance_report(ws.root, now=now)
        assurance = recovery["assurance"]
        status = "ok" if assurance == "current" else "warn"
        detail = (f"{recovery['rehearsals_passed']} passed rehearsal(s); assurance={assurance}; "
                  f"last pass age={recovery['days_since_last_pass']} day(s)")
        remediation = "Run and record a verified PostgreSQL restore rehearsal; investigate the latest failure" if status != "ok" else ""
        checks.append(_check("restore_rehearsal", status, detail, remediation))
    except Exception as exc:  # readiness should report an unreadable evidence log, not crash
        checks.append(_check("restore_rehearsal", "warn", f"Could not read recovery evidence: {exc}",
                             "Inspect logs/recovery-rehearsals.jsonl"))

    statuses = [item["status"] for item in checks]
    overall = "fail" if "fail" in statuses else "warning" if "warn" in statuses else "ready"
    return {"overall": overall, "generated_at": now.isoformat(),
            "summary": {s: statuses.count(s) for s in ("ok", "warn", "fail")}, "checks": checks,
            "limitations": ["Does not connect to tenant databases", "Does not prove backup contents unless a verified restore rehearsal exists",
                            "Does not measure RPO or full service RTO", "Does not perform penetration, concurrency or browser tests"]}
