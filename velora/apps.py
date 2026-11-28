"""Install / uninstall apps on a site; fetch apps from git."""
from __future__ import annotations

import importlib
import re
import shutil
import subprocess

from sqlalchemy import delete, insert

from . import db, site as site_mod
from .db import schema
from .db.system import installed_app
from .document.document import now
from .exceptions import MetaError
from .workspace import APP_NAME_RE, Workspace, WorkspaceError


def _hooks(app: str):
    try:
        return importlib.import_module(f"{app}.hooks")
    except ModuleNotFoundError as e:
        if e.name != f"{app}.hooks":
            raise
        return None


def _call(dotted: str | None):
    if dotted:
        mod, _, fn = dotted.rpartition(".")
        getattr(importlib.import_module(mod), fn)()


def app_version(app: str) -> str:
    try:
        return str(getattr(importlib.import_module(app), "__version__", "0.0.0"))
    except ImportError:
        return "?"


# Apps that ship inside the framework itself (installable on any site without being in the workspace's apps/ folder).
BUNDLED_APPS = ("velora_notify", "velora_search")


def _requires(app: str) -> list[str]:
    try:
        return list(getattr(_hooks(app), "required_apps", []) or [])
    except Exception:  # noqa: BLE001
        return []


def _reachable(app: str) -> set[str]:
    seen: set[str] = set()
    todo = list(_requires(app))
    while todo:
        a = todo.pop()
        if a not in seen:
            seen.add(a)
            todo += _requires(a)
    return seen


def cycle_of(app: str) -> list[str]:
    """Apps that need `app` and that `app` needs back (they can only be installed together, e.g. VeloraERP and ProjectOne)."""
    return sorted(a for a in _reachable(app) if app in _reachable(a) and a != app)


def _importable(app: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(app) is not None
    except (ImportError, ValueError):
        return False


def install_missing_required(ws: Workspace, site: site_mod.Site, log=lambda m: None) -> list[str]:
    """Install, on a site that already has some apps, the apps they require but the site lacks (an app update can add such a need).
    Returns the apps installed. An app that is not available in the workspace is left alone: the upgrade then reports it."""
    ws.activate()
    with site_mod.use(site):
        schema.ensure_system_tables()
        have = site.installed_apps()
        want: list[str] = []
        for a in have:
            for r in sorted(_reachable(a)):
                if r not in have and r not in want and (r in ws.apps() or r in BUNDLED_APPS or _importable(r)):
                    want.append(r)
        done: list[str] = []
        for r in want:
            if r in site.installed_apps():
                continue
            for a in (r, *cycle_of(r)):
                if a not in ws.apps() and a not in BUNDLED_APPS and _importable(a):
                    ws.register_app(a)
            group = [g for g in cycle_of(r) if g not in site.installed_apps()]
            log(f"Installing {r}, which an installed app requires" + (f" (together with {', '.join(group)})" if group else ""))
            install_app(ws, site, r, together=group)
            done += [r, *group]
        return done


def install_app(ws: Workspace, site: site_mod.Site, app: str, together: list[str] | tuple = ()) -> list[str]:
    """Install `app` on `site`: validate its metadata, create its tables, record it, run its after_install hook.
    `together` lists apps that need `app` and that it needs back: they are validated and installed in the same step.
    Everything happens in one transaction (PostgreSQL DDL is transactional), so a failure leaves the site untouched."""
    group = [app, *[g for g in together if g != app]]
    if app not in ws.apps() and app not in BUNDLED_APPS:
        raise WorkspaceError(f"App {app!r} is not in this workspace. Create it with `velora new-app {app}` or fetch it with `velora get-app`.")
    ws.activate()
    with site_mod.use(site):
        schema.ensure_system_tables()
        installed = site.installed_apps()
        if app in installed:
            raise WorkspaceError(f"{app} is already installed on {site.name}. Run `velora migrate` to apply DocType changes.")
        for g in group[1:]:
            if g in installed:
                raise WorkspaceError(f"{g} is already installed on {site.name}.")
        hooks = _hooks(app)
        required_velora = str(getattr(hooks, "required_velora", "") or "").strip()
        if required_velora:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version
            from . import __version__
            try:
                compatible = Version(__version__) in SpecifierSet(required_velora)
            except Exception as exc:
                raise WorkspaceError(f"{app} declares an invalid required_velora specifier {required_velora!r}: {exc}") from None
            if not compatible:
                raise WorkspaceError(f"{app} requires Velora {required_velora}; this framework is {__version__}")
        missing = [r for g in group for r in _requires(g) if r not in installed and r not in group]
        if missing:
            raise WorkspaceError(f"{app} requires {', '.join(missing)}; install {'it' if len(missing) == 1 else 'them'} first "
                                 f"(`velora --site {site.name} install-app {missing[0]}`)")
        from . import optional
        pkgs = optional.check_packages(getattr(hooks, "required_packages", []))
        if pkgs:
            raise WorkspaceError(f"{app} needs Python packages that are not ready: {'; '.join(pkgs)}. Install them with `velora deps install --app {app}`.")
        try:
            site.registry.load([*installed, *group])        # validates every DocType + cross references BEFORE touching the DB
        except MetaError:
            site.load()
            raise
        try:
            from .app_runtime import call_lifecycle_hook
            with db.transaction() as conn:
                for g in group:
                    call_lifecycle_hook(g, "before_install")
                    conn.execute(insert(installed_app).values(name=g, version=app_version(g), installed_on=now()))
                plan = schema.migrate()
                for g in group:
                    call_lifecycle_hook(g, "after_install")
        except Exception:
            site.load()                                      # registry back to what is actually installed
            raise
        site.load()
        from .upgrade import patches, state
        patches.mark_applied(group)                         # a freshly installed app has no old data to patch
        state.stamp(state.recorded_version() or None)
    return plan


def uninstall_app(ws: Workspace, site: site_mod.Site, app: str):
    """Remove an app from the site's installed list. Its tables and data are deliberately kept (never auto-drop data)."""
    ws.activate()
    with site_mod.use(site):
        installed = site.installed_apps()
        if app not in installed:
            raise WorkspaceError(f"{app} is not installed on {site.name}")
        dependents = [a for a in installed if app in getattr(_hooks(a), "required_apps", [])]
        if dependents:
            raise WorkspaceError(f"Cannot uninstall {app}: required by {', '.join(dependents)}")
        from .app_runtime import call_lifecycle_hook
        with db.transaction() as conn:
            call_lifecycle_hook(app, "before_uninstall")
            conn.execute(delete(installed_app).where(installed_app.c.name == app))
            call_lifecycle_hook(app, "after_uninstall")
        site.load()


def get_app(ws: Workspace, url: str, name: str | None = None, branch: str | None = None) -> str:
    """Clone an app from a git repository into apps/ and register it. (Does not install it on any site.)"""
    if not shutil.which("git"):
        raise WorkspaceError("git is required for get-app")
    name = name or re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1]).replace("-", "_").lower()
    if not APP_NAME_RE.match(name):
        raise WorkspaceError(f"Cannot derive a valid app name from {url!r}; pass --name")
    dest = ws.app_path(name)
    if dest.exists():
        raise WorkspaceError(f"apps/{name} already exists")
    cmd = ["git", "clone", "--depth", "1", *(["--branch", branch] if branch else []), url, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        raise WorkspaceError(f"git clone failed: {proc.stderr.strip()[:300]}")
    if not (dest / name / "__init__.py").exists():
        shutil.rmtree(dest, ignore_errors=True)
        raise WorkspaceError(f"{url} is not a Velora app: expected a Python package at {name}/__init__.py")
    ws.register_app(name)
    return name
