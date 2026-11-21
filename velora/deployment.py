"""Controlled workspace-to-workspace application promotion."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from .app_package import build_app_archive, validate_archive, install_package
from .workspace import Workspace, WorkspaceError


def _workspace_at(value: str) -> Workspace | None:
    path = Path(value).expanduser().resolve()
    return Workspace(path) if Workspace.is_workspace(path) else None


def _profiles_file(ws: Workspace) -> Path:
    return ws.root / "config" / "deployment-profiles.json"


def _profiles(ws: Workspace) -> dict:
    path = _profiles_file(ws)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise WorkspaceError("Deployment profile file is unreadable") from None
    if not isinstance(data, dict):
        raise WorkspaceError("Deployment profile file must contain an object")
    return data


def create_profile(ws: Workspace, name: str, source: str, target: str, apps: list[str]) -> dict:
    if not name or not name.replace("_", "").isalnum() or not name[0].isalpha():
        raise WorkspaceError("Profile name must start with a letter and contain only letters, digits or underscores")
    src = Workspace.discover(source)
    dst = Workspace.discover(target)
    if src is None or dst is None:
        raise WorkspaceError("Both source and target must be existing Velora workspaces")
    if src.root == dst.root:
        raise WorkspaceError("Source and target workspaces must be different")
    if not apps:
        raise WorkspaceError("Select at least one application")
    unknown = [a for a in apps if a not in src.apps()]
    if unknown:
        raise WorkspaceError("Applications not found in source workspace: " + ", ".join(unknown))
    profiles = _profiles(ws)
    profiles[name] = {"source": str(src.root), "target": str(dst.root), "apps": list(dict.fromkeys(apps)),
                      "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = _profiles_file(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return {"name": name, **profiles[name]}


def list_profiles(ws: Workspace) -> list[dict]:
    return [{"name": name, **value} for name, value in sorted(_profiles(ws).items())]


def _load_profile(ws: Workspace, name: str):
    profile = _profiles(ws).get(name)
    if not profile:
        raise WorkspaceError(f"Unknown deployment profile: {name}")
    source = Workspace.discover(profile["source"])
    target = Workspace.discover(profile["target"])
    if source is None or target is None:
        raise WorkspaceError("The source or target workspace no longer exists")
    if source.root == target.root:
        raise WorkspaceError("Source and target workspaces must be different")
    return profile, source, target


def build_plan(ws: Workspace, name: str) -> dict:
    from .upgrade.engine import collect_targets
    profile, source, target = _load_profile(ws, name)
    packages = []
    for app in profile["apps"]:
        data, report = build_app_archive(source, app)
        checked = validate_archive(data)
        packages.append({"name": app, "version": report["version"], "required_apps": report["required_apps"],
                         "required_velora": report["required_velora"], "sha256": hashlib.sha256(data).hexdigest(),
                         "size_bytes": len(data), "file_count": checked["file_count"], "valid": checked["valid"]})
    targets = collect_targets(target)
    return {
        "format": "velora-deployment-plan", "format_version": 1, "profile": name,
        "source": str(source.root), "target": str(target.root),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "packages": packages, "target_count": len(targets),
        "targets": [{"id": t.id, "label": t.label} for t in targets],
        "safety": {"database_backups_before_install": True, "application_data_retained_on_uninstall": True,
                   "package_code_validated_before_changes": True},
    }


def promote(ws: Workspace, name: str, *, dry_run: bool = False, log=print) -> dict:
    """Promote selected app source and install on every target company/site.

    All archives are built and validated before target mutation. Every target database
    is backed up before package replacement or installation. On failure, touched
    databases and app source directories are restored from those snapshots.
    """
    from . import provision
    from .lifecycle import install_everywhere
    from .upgrade.engine import collect_targets, restore_target

    profile, source, target = _load_profile(ws, name)
    packages = {}
    selected = set(profile["apps"])
    target.activate()
    for app in profile["apps"]:
        data, app_report = build_app_archive(source, app)
        validate_archive(data)
        packages[app] = (data, app_report)
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
    from .upgrade.versions import code_version
    for app, (_, app_report) in packages.items():
        required = app_report.get("required_velora") or ""
        if required and Version(code_version()) not in SpecifierSet(required):
            raise WorkspaceError(f"{app} requires Velora {required}; current version is {code_version()}")
        missing = set(app_report.get("required_apps") or []) - selected - set(target.apps())
        if missing:
            raise WorkspaceError(f"{app} requires applications not present in the target or this promotion: {', '.join(sorted(missing))}")

    targets = collect_targets(target)
    if not targets:
        raise WorkspaceError("Target workspace has no company or site databases")
    if dry_run:
        return {"status": "dry_run", "profile": name, "packages": [{"name": a, "version": r["version"]} for a, (_, r) in packages.items()],
                "targets": [{"id": t.id, "label": t.label} for t in targets], "changed": False}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snapshot = target.root / "backups" / f"deployment-{name}-{stamp}"
    snapshot.mkdir(parents=True, exist_ok=False)
    db_files = {}
    code_backups = {}
    touched_apps = []
    previously_registered = set(target.apps())
    report = {"status": "running", "profile": name, "snapshot": str(snapshot), "packages": [], "targets": []}
    try:
        for t in targets:
            log(f"Backing up {t.label} before deployment ...")
            db_files[t.id] = provision.backup_database(dict(t.cfg), t.sqlite_file, snapshot, t.id)
        (snapshot / "manifest.json").write_text(json.dumps({
            "kind": "velora-deployment", "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "profile": name, "databases": {k: v.name for k, v in db_files.items()},
        }, indent=2), encoding="utf-8")

        for app, (data, app_report) in packages.items():
            dest = target.app_path(app)
            if dest.exists():
                saved = snapshot / "code" / app
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(dest, saved)
                code_backups[app] = saved
            else:
                code_backups[app] = None
            info = validate_archive(data)
            install_package(target, data, overwrite=dest.exists())
            touched_apps.append(app)
            # The current process may have imported the target's previous package version.
            for module_name in list(sys.modules):
                if module_name == app or module_name.startswith(app + "."):
                    sys.modules.pop(module_name, None)
            importlib.invalidate_caches()
            report["packages"].append({"name": app, "version": info["version"], "status": "staged"})
        target.activate()

        failures = []
        for app in profile["apps"]:
            log(f"Installing {app} on target companies/sites ...")
            result = install_everywhere(target, app, do_restart=False, log=log)
            report["targets"].append({"app": app, "results": result["results"]})
            if any(row["status"] == "failed" for row in result["results"]):
                failures.append(app)
        if failures:
            raise WorkspaceError("Application installation failed for: " + ", ".join(failures))

        # Bring all target schemas/patches to the current framework code, with its own safety snapshots.
        from .upgrade.engine import UpgradeEngine
        upgrade = UpgradeEngine(target, backup=True, log=log).run()
        report["upgrade"] = upgrade
        if upgrade["status"] not in ("success", "up_to_date"):
            raise WorkspaceError(f"Target database upgrade ended with status {upgrade['status']}")
        from .lifecycle import restart
        report["restart"] = restart(target, log)
        report["status"] = "success"
        report["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return report
    except Exception as exc:
        rollback = []
        for t in reversed(targets):
            if t.id not in db_files:
                continue
            try:
                restore_target(t, db_files[t.id])
                rollback.append({"target": t.id, "restored": True})
            except Exception as restore_exc:
                rollback.append({"target": t.id, "restored": False, "error": str(restore_exc)})
        for app in reversed(touched_apps):
            dest = target.app_path(app)
            backup = code_backups.get(app)
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                if backup and backup.exists():
                    shutil.copytree(backup, dest)
            except Exception as code_exc:
                rollback.append({"app": app, "restored": False, "error": str(code_exc)})
        for app in touched_apps:
            if app not in previously_registered:
                try:
                    target.unregister_app(app)
                except Exception as registration_exc:
                    rollback.append({"app": app, "registration_restored": False, "error": str(registration_exc)})
        report.update(status="rolled_back", error=str(exc), rollback=rollback,
                      finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return report
