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


def install_app(ws: Workspace, site: site_mod.Site, app: str) -> list[str]:
    """Install `app` on `site`: validate its metadata, create its tables, record it, run its after_install hook.
    Everything happens in one transaction (PostgreSQL DDL is transactional), so a failure leaves the site untouched."""
    if app not in ws.apps() and app not in BUNDLED_APPS:
        raise WorkspaceError(f"App {app!r} is not in this workspace. Create it with `velora new-app {app}` or fetch it with `velora get-app`.")
    ws.activate()
    with site_mod.use(site):
        schema.ensure_system_tables()
        installed = site.installed_apps()
        if app in installed:
            raise WorkspaceError(f"{app} is already installed on {site.name}. Run `velora migrate` to apply DocType changes.")
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
        missing = [r for r in getattr(hooks, "required_apps", []) if r not in installed]
        if missing:
            raise WorkspaceError(f"{app} requires {', '.join(missing)}; install {'it' if len(missing) == 1 else 'them'} first "
                                 f"(`velora --site {site.name} install-app {missing[0]}`)")
        from . import optional
        pkgs = optional.check_packages(getattr(hooks, "required_packages", []))
        if pkgs:
            raise WorkspaceError(f"{app} needs Python packages that are not ready: {'; '.join(pkgs)}. Install them with `velora deps install --app {app}`.")
        try:
            site.registry.load([*installed, app])           # validates every DocType + cross references BEFORE touching the DB
        except MetaError:
            site.load()
            raise
        try:
            from .app_runtime import call_lifecycle_hook
            with db.transaction() as conn:
                call_lifecycle_hook(app, "before_install")
                conn.execute(insert(installed_app).values(name=app, version=app_version(app), installed_on=now()))
                plan = schema.migrate()
                call_lifecycle_hook(app, "after_install")
        except Exception:
            site.load()                                      # registry back to what is actually installed
            raise
        site.load()
        from .upgrade import patches, state
        patches.mark_applied([app])                           # a freshly installed app has no old data to patch
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
