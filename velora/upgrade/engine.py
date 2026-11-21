"""`velora upgrade`: bring every database in a workspace up to the installed code, safely.

    lock → plan → maintenance ON → back up every database that needs it → upgrade control plane, then each company/site
    (schema sync + data patches + version stamp) → health check → maintenance OFF

ALL-OR-NOTHING by default: if any database fails, every database already touched is restored from the pre-upgrade backup, so the
workspace is exactly as it was (the code is then rolled back by `velora update`). `--partial` instead leaves a failed database
in "upgrade pending" (it answers 503) and upgrades the rest.
"""
from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import db, provision, site as site_mod
from ..db import schema
from ..exceptions import VeloraError
from ..workspace import Workspace, WorkspaceError
from ..controlplane.directory import PlaneDirectory
from . import backup as bk, maintenance, patches, state
from .versions import app_version, code_version, compare, satisfies


class UpgradeError(WorkspaceError):
    pass


@dataclass
class Target:
    kind: str                      # control_plane | company | site
    id: str
    label: str
    site: site_mod.Site | None = None
    plane: object | None = None
    sqlite_file: Path | None = None
    cfg: dict = field(default_factory=dict)          # backup/restore connection (may hold a password - never logged)
    company: object | None = None                    # CompanyInfo, so patches can call velora.current_company()

    @property
    def is_sqlite(self) -> bool:
        return self.cfg.get("db_type", "sqlite") == "sqlite"


def _require_file(label: str, f: Path | None, kind: str) -> None:
    if f is not None and not f.exists():
        raise UpgradeError(f"{label}: its database file is MISSING ({f}). Restore it from a backup (velora restore <backup> {kind} --yes); "
                           "do not run upgrades until it is back, or an empty database would be created in its place.")


def collect_targets(ws: Workspace, only: list[str] | None = None) -> list[Target]:
    from ..controlplane import ControlPlane
    out: list[Target] = []
    plane = None
    if ControlPlane.exists(ws):
        plane = ControlPlane.open(ws)
        cp_cfg = dict(plane.cfg)
        if cp_cfg.get("db_type") == "sqlite":
            _require_file("Control plane", plane.platform_dir / cp_cfg.get("db_name", "control.db"), "--control-plane")
        out.append(Target("control_plane", "control-plane", "Control plane", plane=plane, cfg=cp_cfg,
                          sqlite_file=(plane.platform_dir / cp_cfg.get("db_name", "control.db")) if cp_cfg.get("db_type") == "sqlite" else None))
        for co in plane.registry.list_companies():
            if co["status"] not in ("active", "suspended"):
                continue
            cfg = plane.router.db_config(co)
            if co["db_engine"] == "sqlite":
                _require_file(f"{co['id']} {co['name']}", plane.sqlite_path(co), f"--company {co['id']}")
            from ..company import CompanyInfo
            tenant = plane.registry.get_tenant(co["tenant_id"]) or {}
            out.append(Target("company", co["id"], f"{co['id']} {co['name']}", site=plane.router.site_for({**co, "status": "active"}), plane=plane,
                              cfg=cfg, sqlite_file=plane.sqlite_path(co) if co["db_engine"] == "sqlite" else None,
                              company=CompanyInfo(co["id"], co["name"], co["tenant_id"], tenant.get("name", ""), PlaneDirectory(plane, co["id"]))))
    for name in ws.sites():
        d = ws.site_path(name)
        cfg = site_mod.read_site_config(d)
        if cfg.get("db_type", "sqlite") == "sqlite":
            _require_file(f"site {name}", d / cfg.get("db_name", "site.db"), f"--site {name}")
        site = site_mod.load_site(d)
        out.append(Target("site", name, f"site {name}", site=site, cfg=cfg,
                          sqlite_file=(d / cfg.get("db_name", "site.db")) if cfg.get("db_type", "sqlite") == "sqlite" else None))
    if only:
        wanted = set(only)
        unknown = wanted - {t.id for t in out}
        if unknown:
            raise UpgradeError(f"Unknown target(s): {', '.join(sorted(unknown))}. Known: {', '.join(t.id for t in out) or 'none'}")
        out = [t for t in out if t.id in wanted]
    return out


# ---- per-target: inspect and upgrade -----------------------------------------------------------------------------
def _check_compat(site: site_mod.Site, apps: list[str]) -> None:
    from ..apps import _hooks
    code = code_version()
    for app in apps:
        spec = getattr(_hooks(app), "required_velora", None)
        if spec and not satisfies(spec, code):
            raise UpgradeError(f"{app} requires velora {spec}, but velora {code} is installed. Update velora, or use a compatible release of {app}.")
        from .. import optional
        pkgs = optional.check_packages(getattr(_hooks(app), "required_packages", []))
        if pkgs:
            raise UpgradeError(f"{app} needs Python packages that are not ready: {'; '.join(pkgs)}. Run `velora deps install --app {app}` first.")
        recorded = _recorded_app_versions().get(app)
        if recorded and compare(app_version(app), recorded) < 0:
            raise UpgradeError(f"{app}: this database is at version {recorded} but the code is {app_version(app)} (a downgrade). "
                               "Install the newer code or restore a backup.")


def _recorded_app_versions() -> dict:
    from sqlalchemy import select

    from ..db.system import installed_app
    with db.transaction() as conn:
        return {r[0]: r[1] for r in conn.execute(select(installed_app.c.name, installed_app.c.version))}


def inspect_target(t: Target) -> dict:
    """What an upgrade WOULD do to this target (nothing is changed)."""
    if t.kind == "control_plane":
        plan = t.plane.migrate(dry_run=True)
        st, rec = t.plane.pending_upgrade()
        return {"id": t.id, "label": t.label, "version": rec, "gate": st, "schema": [p for p in plan if not p.startswith("WARNING")],
                "warnings": [p for p in plan if p.startswith("WARNING")], "patches": []}
    with site_mod.use(t.site):
        t.site.load()
        apps = t.site.installed_apps()
        _check_compat(t.site, apps)
        plan = schema.migrate(dry_run=True)
        t.site.gate_cache = None
        st, rec = state.gate_state(state.recorded_version())
        pend = patches.pending(apps, "pre_model_sync") + patches.pending(apps, "post_model_sync")
    return {"id": t.id, "label": t.label, "version": rec, "gate": st, "schema": [p for p in plan if not p.startswith("WARNING")],
            "warnings": [p for p in plan if p.startswith("WARNING")], "patches": pend}


def needs_upgrade(info: dict) -> bool:
    return info["gate"] != "ok" or bool(info["schema"]) or bool(info["patches"])


def upgrade_target(t: Target, log=lambda m: None) -> dict:
    """Run the upgrade for one target. Raises on failure (the caller decides about rollback)."""
    if t.kind == "control_plane":
        plan = t.plane.migrate()
        return {"schema": [p for p in plan if not p.startswith("WARNING")], "patches": []}
    from contextlib import ExitStack

    from ..company import company_context
    with ExitStack() as stack:
        stack.enter_context(site_mod.use(t.site))
        if t.company is not None:                             # patches run INSIDE the company they are migrating
            stack.enter_context(company_context(t.company))
        schema.ensure_system_tables()
        t.site.load()
        apps = t.site.installed_apps()
        _check_compat(t.site, apps)
        from ..app_runtime import call_lifecycle_hook
        for app in apps:
            call_lifecycle_hook(app, "before_migrate")
        pre = patches.run(apps, "pre_model_sync", log)
        plan = schema.migrate()
        t.site.load()
        post = patches.run(apps, "post_model_sync", log)
        for app in apps:
            call_lifecycle_hook(app, "after_migrate")
        state.stamp()
        if t.kind == "company" and t.plane is not None:
            t.plane.registry.update_company(t.id, schema_version=code_version())
    return {"schema": [p for p in plan if not p.startswith("WARNING")], "warnings": [p for p in plan if p.startswith("WARNING")], "patches": pre + post}


def health_check(t: Target) -> None:
    if t.kind == "control_plane":
        t.plane._gate = None
        st, rec = t.plane.pending_upgrade()
        if st != "ok":
            raise UpgradeError(f"control plane is still at {rec}")
        return
    t.site.gate_cache = None
    with site_mod.use(t.site):
        t.site.load()
        with db.transaction() as conn:
            conn.exec_driver_sql("select 1")
        st, rec = state.check_site(t.site)
    if st != "ok":
        raise UpgradeError(f"{t.label} is still at {rec}")


def restore_target(t: Target, backup_file: Path) -> None:
    if t.site is not None:
        t.site.dispose()
        t.site.gate_cache = None
    if t.plane is not None and t.kind == "control_plane":
        t.plane.engine.dispose()
    bk.restore_database(t.cfg, t.sqlite_file, backup_file)
    if t.site is not None:
        with site_mod.use(t.site):
            t.site.load()


# ---- lock -----------------------------------------------------------------------------------------------------------
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def upgrade_lock(ws: Workspace):
    path = ws.root / ".upgrade.lock"
    owned = False
    if path.exists():
        try:
            pid = int(json.loads(path.read_text()).get("pid", 0))
        except (ValueError, OSError):
            pid = 0
        if pid and pid == os.getppid():
            yield False                                       # our parent (`velora update`) holds it on our behalf
            return
        if pid and _alive(pid):
            raise UpgradeError(f"Another upgrade is already running (pid {pid}). If that is wrong, delete {path}")
        path.unlink(missing_ok=True)                          # stale lock from a crashed run
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise UpgradeError("Another upgrade started at the same moment") from None
    with os.fdopen(fd, "w") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    owned = True
    try:
        yield True
    finally:
        if owned:
            path.unlink(missing_ok=True)


# ---- orchestrator ---------------------------------------------------------------------------------------------------
class UpgradeEngine:
    def __init__(self, ws: Workspace, *, partial: bool = False, backup: bool = True, only: list[str] | None = None, force: bool = False,
                 log=print, keep_snapshots: int = 5):
        self.ws, self.partial, self.backup, self.only, self.force, self.log, self.keep = ws, partial, backup, only, force, log, keep_snapshots

    def plan(self) -> list[dict]:
        return [inspect_target(t) for t in collect_targets(self.ws, self.only)]

    def run(self, dry_run: bool = False) -> dict:
        ws, log = self.ws, self.log
        ws.activate()
        report: dict = {"status": "running", "from": None, "to": code_version(), "started": _now(), "targets": [], "snapshot": None, "dry_run": dry_run}
        with upgrade_lock(ws):
            targets = collect_targets(ws, self.only)
            infos = {t.id: inspect_target(t) for t in targets}
            report["targets"] = [{"id": i["id"], "label": i["label"], "from": i["version"], "needs_upgrade": needs_upgrade(i), "schema_changes": len(i["schema"]),
                                  "patches": i["patches"], "warnings": i["warnings"], "status": "pending" if needs_upgrade(i) else "up_to_date"} for i in infos.values()]
            todo = [t for t in targets if self.force or needs_upgrade(infos[t.id])]
            if dry_run or not todo:
                report["status"] = "dry_run" if dry_run else "up_to_date"
                report["finished"] = _now()
                return report

            owns_maintenance = maintenance.status(ws) is None
            if owns_maintenance:
                maintenance.enable(ws)
            snapshot, files = None, {}
            touched: list[Target] = []
            failures: list[tuple[Target, Exception]] = []
            try:
                if self.backup:
                    snapshot = ws.root / "backups" / f"upgrade-{bk.timestamp()}"
                    snapshot.mkdir(parents=True, exist_ok=True)
                    for t in todo:
                        log(f"Backing up {t.label} ...")
                        files[t.id] = self._backup(t, snapshot)
                    (snapshot / "manifest.json").write_text(json.dumps(
                        {"created": _now(), "code_version": code_version(), "targets": {k: v.name for k, v in files.items()}}, indent=2))
                    report["snapshot"] = str(snapshot)
                for t in todo:
                    row = next(r for r in report["targets"] if r["id"] == t.id)
                    log(f"Upgrading {t.label} ({infos[t.id]['version'] or 'unversioned'} -> {code_version()}) ...")
                    touched.append(t)
                    try:
                        res = upgrade_target(t, log)
                        health_check(t)
                        row.update(status="upgraded", patches_run=res["patches"], schema_applied=res["schema"])
                    except Exception as e:  # noqa: BLE001 - every failure is attributed to its target and handled below
                        row.update(status="failed", error=_short(e))
                        failures.append((t, e))
                        log(f"  FAILED: {_short(e)}")
                        if not self.partial:
                            break
                if failures and not self.partial:
                    self._rollback(touched, files, report)
                    report["status"] = "rolled_back" if files else "failed"      # never claim a rollback that could not happen
                elif failures:
                    report["status"] = "partial"
                else:
                    report["status"] = "success"
                    if snapshot:
                        self._prune(ws)
            finally:
                if owns_maintenance:
                    maintenance.disable(ws)
            report["finished"] = _now()
            return report

    def _backup(self, t: Target, snapshot: Path) -> Path:
        cfg = {k: v for k, v in t.cfg.items()}
        out = provision.backup_database(cfg, t.sqlite_file, snapshot, t.id)
        bk.verify_backup(out)
        return out

    def _rollback(self, touched: list[Target], files: dict, report: dict) -> None:
        if not files:
            report["rollback"] = "no backup was taken (--no-backup): databases could NOT be restored automatically"
            return
        results = []
        for t in reversed(touched):
            if t.id not in files:
                continue
            try:
                self.log(f"Rolling back {t.label} from {files[t.id].name} ...")
                restore_target(t, files[t.id])
                results.append({"id": t.id, "restored": True})
            except Exception as e:  # noqa: BLE001 - never hide a failed rollback
                results.append({"id": t.id, "restored": False, "error": _short(e), "manual": f"velora restore {files[t.id]} --{ 'control-plane' if t.kind == 'control_plane' else t.kind.replace('company', 'company ' + t.id).replace('site', 'site ' + t.id)} --yes"})
        report["rollback"] = results
        for row in report["targets"]:
            if any(r["id"] == row["id"] and r["restored"] for r in results):
                row["status"] = "rolled_back" if row["status"] != "failed" else "failed (restored)"

    def _prune(self, ws: Workspace) -> None:
        snaps = sorted((ws.root / "backups").glob("upgrade-*"))
        for old in snaps[: max(0, len(snaps) - self.keep)]:
            shutil.rmtree(old, ignore_errors=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _short(e: Exception) -> str:
    msg = str(e).strip().splitlines()
    return f"{type(e).__name__}: {msg[0][:300] if msg else ''}" if not isinstance(e, (VeloraError, WorkspaceError)) else (msg[0][:300] if msg else type(e).__name__)
