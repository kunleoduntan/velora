"""Install, uninstall and keep an installation current - each as ONE command that does every step itself.

    velora install-app <name | git URL | folder>     fetch it, install its Python packages, install it on EVERY company, restart
    velora uninstall-app <name>                      back up, remove it from EVERY company (and optionally its data and code), restart
    velora update                                    fetch new code, packages, back up, upgrade every database, enable new built-in features, restart; undo it all if anything fails

Nothing here asks you to run another command first: missing Python packages are installed, required apps are installed before the app that needs them,
a failure in one company never stops the others, and every change that can lose data is preceded by a backup.
"""
from __future__ import annotations

import importlib
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from . import apps as apps_mod
from . import optional
from . import site as site_mod
from .apps import BUNDLED_APPS, _hooks
from .company import company_context
from .permissions import ADMINISTRATOR, session_as
from .upgrade.engine import collect_targets
from .workspace import Workspace, WorkspaceError

APP_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
BUILTIN_DEFAULT_APPS = ("velora_notify", "velora_search")           # what a new installation gets (notifications and global search)


# ------------------------------------------------------------------ targets ------------------------------------------------------------------
def targets(ws: Workspace, only: list[str] | None = None):
    """Every company (platform mode) and site this workspace serves, or just those named. The control plane is never an app target."""
    pool = [t for t in collect_targets(ws, only) if t.kind != "control_plane"]
    if only and not pool:
        raise WorkspaceError(f"No such company or site: {', '.join(only)}")
    return pool


@contextmanager
def in_target(t):
    with site_mod.use(t.site), session_as(ADMINISTRATOR):
        if t.company is not None:
            with company_context(t.company):
                yield
        else:
            yield


def installed_in(ws: Workspace, t) -> list[str]:
    with in_target(t):
        return list(t.site.installed_apps())


# ------------------------------------------------------------------ finding and fetching the app ------------------------------------------------------------------
def _is_url(s: str) -> bool:
    return "://" in s or s.startswith("git@") or s.endswith(".git")


def resolve_source(ws: Workspace, source: str, name: str | None = None, branch: str | None = None, log=print) -> str:
    """The app's name, after fetching it into the workspace if needed. `source` is an app already here, a built-in app, a git URL, or a folder."""
    ws.activate()
    if source in ws.apps() or source in BUNDLED_APPS:
        return source
    if _is_url(source):
        log(f"Fetching {source} ...")
        return apps_mod.get_app(ws, source, name, branch)
    p = Path(source).expanduser()
    if p.is_dir():
        p = p.resolve()
        nm = name or p.name.replace("-", "_").lower()
        if not APP_NAME.match(nm):
            raise WorkspaceError(f"Cannot use {p.name!r} as an app name; pass --name")
        if nm in ws.apps():
            raise WorkspaceError(f"apps/{nm} already exists")
        log(f"Adding {p} ...")
        if (p / ".git").exists():
            return apps_mod.get_app(ws, str(p), nm, branch)
        dest = ws.app_path(nm)
        shutil.copytree(p, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "node_modules"))
        if not (dest / nm / "__init__.py").exists():
            shutil.rmtree(dest, ignore_errors=True)
            raise WorkspaceError(f"{p} is not a Velora app: expected a Python package at {nm}/__init__.py")
        ws.register_app(nm)
        return nm
    known = ", ".join(sorted(set(ws.apps()) | set(BUNDLED_APPS)))
    raise WorkspaceError(f"{source!r} is not an app in this workspace, a built-in app, a git URL or a folder. Available here: {known}")


def required_packages(app: str) -> list[str]:
    try:
        return list(getattr(importlib.import_module(f"{app}.hooks"), "required_packages", []) or [])
    except ImportError:
        return []


def ensure_packages(ws: Workspace, app: str, install: bool = True, log=print) -> list[str]:
    """Make sure the app's Python packages are present: the `required_packages` it declares and the dependencies in its pyproject.toml. Returns what was installed."""
    from .upgrade.update import _app_requirements
    candidates = list(dict.fromkeys(required_packages(app) + ([] if app in BUNDLED_APPS else _app_requirements(ws, app))))
    todo = [r for r in candidates if optional.check_packages([r])]               # those that are missing or too old
    if not todo:
        return []
    if not install:
        raise WorkspaceError(f"{app} needs Python packages: {', '.join(todo)}")
    log(f"Installing {app}'s Python packages: {', '.join(todo)} ...")
    try:
        optional.install(todo)
    except optional.DependencyError as e:
        raise WorkspaceError(f"Could not install the packages {app} needs, so nothing was changed. {e}") from None
    return todo


def _required_apps(app: str) -> list[str]:
    try:
        return list(getattr(_hooks(app), "required_apps", []) or [])
    except Exception:  # noqa: BLE001
        return []


def _install_order(app: str, seen: tuple = ()) -> list[str]:
    """Apps this one needs first, then the app itself."""
    out: list[str] = []
    for dep in _required_apps(app):
        if dep not in seen:
            out += [d for d in _install_order(dep, (*seen, app)) if d not in out]
    return [*out, app]


# ------------------------------------------------------------------ restart ------------------------------------------------------------------
def restart(ws: Workspace, log=print) -> dict | None:
    """Run the restart command the installer configured (None if there is none: then say so)."""
    cmd = ws.common_config().get("update", {}).get("restart_command")
    if not cmd:
        log("No restart command is configured: restart the server to use the change.")
        return None
    log("Restarting ...")
    try:
        rc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180)
        res = {"ok": rc.returncode == 0, "output": (rc.stderr or rc.stdout).strip()[-300:]}
    except Exception as e:  # noqa: BLE001
        res = {"ok": False, "output": str(e)}
    log("Restarted." if res["ok"] else f"Restart failed: {res['output']}")
    return res


# ------------------------------------------------------------------ install ------------------------------------------------------------------
def _install_on(ws: Workspace, t, order: list[str]) -> tuple[str, list[str]]:
    """Install the apps in `order` on one target. Returns (status, apps actually installed now)."""
    done: list[str] = []
    for a in order:
        if a in installed_in(ws, t):
            continue
        with in_target(t):
            apps_mod.install_app(ws, t.site, a)
        done.append(a)
    return ("installed" if done else "already installed"), done


def install_everywhere(ws: Workspace, source: str, *, only: list[str] | None = None, name: str | None = None, branch: str | None = None,
                       with_packages: bool = True, do_restart: bool = True, log=print) -> dict:
    ws.activate()
    app = resolve_source(ws, source, name, branch, log)
    ws.activate()                                                            # the app may be new: put its folder on the import path so we can read its hooks
    importlib.invalidate_caches()
    order = _install_order(app)
    for a in order[:-1]:
        if a not in ws.apps() and a not in BUNDLED_APPS:
            raise WorkspaceError(f"{app} needs the app {a}, which is not available here. Add it first (a git URL or folder works: `velora install-app <url>`).")
    for a in order:                                                          # packages first: nothing is touched in any database until they are in place
        ensure_packages(ws, a, install=with_packages, log=log)
    pool = targets(ws, only)
    if not pool:
        raise WorkspaceError("There is no company or site to install on yet. Create one first (`velora quickstart`, or `velora company create`).")
    results = []
    for t in pool:
        try:
            status, done = _install_on(ws, t, order)
            results.append({"target": t.id, "label": t.label, "status": status, "installed": done})
            log(f"  {t.label}: {status}" + (f" ({', '.join(done)})" if done and done != [app] else ""))
        except Exception as e:  # noqa: BLE001 - one company's problem must not stop the others
            msg = str(e) if isinstance(e, WorkspaceError) else f"{type(e).__name__}: {e}"       # an unexpected error keeps its type, so a developer can see what blew up
            results.append({"target": t.id, "label": t.label, "status": "failed", "error": msg})
            log(f"  {t.label}: FAILED - {msg}")
    _forget_opt_out(ws, app, [r["target"] for r in results if r["status"] in ("installed", "already installed")])        # you installed it again: it is wanted there
    rep = {"app": app, "results": results, "restart": None}
    if do_restart and any(r["status"] == "installed" for r in results):
        rep["restart"] = restart(ws, log)
    if any(r["status"] == "installed" for r in results):
        from . import eventlog
        steps = [{"text": f"{r['label']}: {r['status']}" + (f" ({', '.join(r['installed'])})" if r.get("installed") and r["installed"] != [app] else "") + (f" - {r['error']}" if r.get("error") else ""), "ok": r["status"] != "failed"} for r in results]
        if rep["restart"] and rep["restart"].get("ok"):
            steps.append({"text": "Restarted the server", "ok": True})
        eventlog.record(ws, "install-app", f"Installed the app {app}", steps, ok=not any(r["status"] == "failed" for r in results), app=app)
    return rep


def _skips(ws: Workspace) -> dict:
    return {k: list(v) for k, v in (ws.common_config().get("default_apps_skip") or {}).items()}


def _remember_opt_out(ws: Workspace, app: str, removed_ids: list[str], everywhere: bool) -> None:
    """Uninstalling a default app is a decision: `velora update` must never quietly bring it back."""
    cfg = ws.common_config()
    if app not in (cfg.get("default_apps") or []):
        return
    if everywhere:
        ws.update_config(default_apps=[a for a in cfg["default_apps"] if a != app])           # no company has it any more: stop making it the default
        return
    skip = _skips(ws)
    skip[app] = sorted({*skip.get(app, []), *removed_ids})
    ws.update_config(default_apps_skip=skip)


def _forget_opt_out(ws: Workspace, app: str, ids: list[str]) -> None:
    skip = _skips(ws)
    if app in skip:
        left = [i for i in skip[app] if i not in ids]
        if left:
            skip[app] = left
        else:
            skip.pop(app)
        ws.update_config(default_apps_skip=skip or None)


# ------------------------------------------------------------------ uninstall ------------------------------------------------------------------
def backup_target(ws: Workspace, t, folder: str, label: str) -> Path:
    from . import provision
    return provision.backup_database(dict(t.cfg), t.sqlite_file, ws.root / "backups" / folder, label)


def _app_doctypes(app: str) -> list[str]:
    from .meta.registry import registry
    return [m.name for m in registry.all() if m.app == app]


def _purge_tables(app: str, doctypes: list[str], tables: list) -> list[str]:
    """DROP the app's tables (its data!). `tables` were captured BEFORE the app was uninstalled (afterwards its DocTypes are no longer known). Child tables are DocTypes too."""
    from sqlalchemy import bindparam, delete, inspect, text

    from . import db
    from .db.system import pg_object
    dropped = []
    with db.transaction() as conn:
        insp = inspect(conn)
        for t in tables:
            if insp.has_table(t.name):
                t.drop(conn)
                dropped.append(t.name)
        conn.execute(delete(pg_object).where(pg_object.c.app == app))
        if insp.has_table("tab_search_index") and doctypes:                   # a search index must not keep pointing at documents that no longer exist
            conn.execute(text("DELETE FROM tab_search_index WHERE ref_doctype IN :d").bindparams(bindparam("d", expanding=True)), {"d": doctypes})
    return dropped


def uninstall_everywhere(ws: Workspace, app: str, *, only: list[str] | None = None, purge: bool = False, backup: bool = True, remove_code: bool = False,
                         do_restart: bool = True, log=print) -> dict:
    ws.activate()
    if app not in ws.apps() and app not in BUNDLED_APPS:
        raise WorkspaceError(f"{app!r} is not an app of this workspace")
    if purge and not backup:
        raise WorkspaceError("--purge deletes the app's data, so it always takes a backup first (remove --no-backup)")
    if remove_code and app in BUNDLED_APPS:
        raise WorkspaceError(f"{app} is built into Velora: its code cannot be removed (it can still be uninstalled from companies)")
    pool = targets(ws, only)
    affected = [t for t in pool if app in installed_in(ws, t)]
    for t in affected:                                                       # check EVERYTHING before changing ANYTHING
        deps = [a for a in installed_in(ws, t) if app in _required_apps(a)]
        if deps:
            raise WorkspaceError(f"Cannot uninstall {app}: {t.label} has {', '.join(deps)} installed, which needs it. Uninstall that first. Nothing was changed.")
    if remove_code:
        chosen = {t.id for t in pool}
        still = [t.label for t in targets(ws) if t.id not in chosen and app in installed_in(ws, t)]
        if still:
            raise WorkspaceError(f"Cannot remove the code of {app}: it is still installed on {', '.join(still)}. Nothing was changed.")
    results = []
    if not affected:
        log(f"{app} is not installed on {'those' if only else 'any'} companies.")
    for t in affected:
        r: dict = {"target": t.id, "label": t.label}
        try:
            if backup:
                r["backup"] = str(backup_target(ws, t, "pre-uninstall", f"{app}-{t.id}"))
            with in_target(t):
                doctypes = _app_doctypes(app) if purge else []
                from .db.tables import get_table
                tables = [get_table(d) for d in doctypes]                    # captured now: after the uninstall these DocTypes are gone
                apps_mod.uninstall_app(ws, t.site, app)
                if purge:
                    r["dropped_tables"] = _purge_tables(app, doctypes, tables)
            r["status"] = "uninstalled" + (" and its data deleted" if purge else " (data kept)")
        except Exception as e:  # noqa: BLE001
            r.update(status="failed", error=str(e))
        results.append(r)
        log(f"  {t.label}: {r['status']}" + (f"  [backup: {r['backup']}]" if r.get("backup") else "") + (f" - {r['error']}" if r.get("error") else ""))
    done_ids = [r["target"] for r in results if r["status"].startswith("uninstalled")]
    if done_ids:
        _remember_opt_out(ws, app, done_ids, everywhere=not only)
    rep = {"app": app, "results": results, "code_removed": False, "restart": None}
    if remove_code and affected and not any(r["status"] == "failed" for r in results):
        shutil.rmtree(ws.app_path(app), ignore_errors=True)
        rep["code_removed"] = True
        log(f"Removed apps/{app}.")
    if do_restart and any(r["status"].startswith("uninstalled") for r in results):
        rep["restart"] = restart(ws, log)
    if any(r["status"].startswith("uninstalled") for r in results):
        from . import eventlog
        steps = [{"text": f"{r['label']}: {r['status']}" + (" - a backup was taken first" if r.get("backup") else ""), "ok": r["status"] != "failed"} for r in results]
        eventlog.record(ws, "uninstall-app", f"Removed the app {app}", steps, ok=not any(r["status"] == "failed" for r in results), app=app)
    return rep


# ------------------------------------------------------------------ keeping current ------------------------------------------------------------------
def ensure_default_apps(ws: Workspace, apps: list[str] | tuple[str, ...], log=print) -> list[dict]:
    """Install the built-in features (notifications, search ...) on every company that lacks them. Quiet when there is nothing to do."""
    out = []
    skip = _skips(ws)
    for app in apps:
        if app not in ws.apps() and app not in BUNDLED_APPS:
            continue
        for t in targets(ws):
            if app in installed_in(ws, t) or t.id in skip.get(app, []):                      # present already, or removed on purpose
                continue
            try:
                order = _install_order(app)
                for a in order:
                    ensure_packages(ws, a, log=log)
                _, done = _install_on(ws, t, order)
                out.append({"target": t.id, "app": app, "status": "installed"})
                log(f"  Enabled {app} on {t.label}")
            except Exception as e:  # noqa: BLE001
                out.append({"target": t.id, "app": app, "status": "failed", "error": str(e)})
                log(f"  Could not enable {app} on {t.label}: {e}")
    return out


def ensure_all_packages(ws: Workspace, log=print) -> list[str]:
    """After new code arrives: the packages every app declares, and the optional extras YOU chose (`velora deps install pdf`, `install.sh --extras`), at the versions now required."""
    done: list[str] = []
    for a in sorted({*ws.apps(), *BUNDLED_APPS}):
        done += ensure_packages(ws, a, log=log)
    for name in ws.common_config().get("extras", []):
        if name not in optional.EXTRAS:
            continue
        todo = [r["requirement"] for r in optional.status(name)["requirements"] if not r["ok"]]
        if not todo:
            continue
        log(f"Updating the '{name}' packages: {', '.join(todo)} ...")
        try:
            optional.install(todo, upgrade=True)
            done += todo
        except optional.DependencyError as e:
            log(f"  Could not update the '{name}' packages ({str(e).splitlines()[0]}); continuing.")
    return list(dict.fromkeys(done))


def upgrade_if_needed(ws: Workspace, log=print) -> dict | None:
    """Used when the server starts: if the code is newer than a database, upgrade it now (with a backup, rolling back on failure) instead of showing 'upgrade pending'."""
    from .upgrade.engine import UpgradeEngine, inspect_target, needs_upgrade
    pending = [t for t in collect_targets(ws) if needs_upgrade(inspect_target(t))]
    if not pending:
        return None
    log(f"{len(pending)} database(s) need upgrading to this version; doing it now (backup first, automatic rollback on failure) ...")
    rep = UpgradeEngine(ws, partial=True, backup=True, log=log).run()
    from . import eventlog
    title, ok, steps, details = eventlog.from_update_report({"status": rep["status"], "upgrade": rep})
    eventlog.record(ws, "upgrade", "Databases upgraded automatically on start" if ok else title.replace("Update", "Automatic upgrade"), steps, ok=ok)
    return rep
