"""A Velora workspace (the equivalent of a bench).

    myworkspace/
      apps/                 app source packages (each a Python package; listed in sites/apps.txt)
      sites/
        apps.txt            apps available in this workspace
        common_site_config.json
        currentsite.txt     default site for CLI commands (`velora use`)
        erp.local/          one directory per site: site_config.json, private/, public/
      config/  logs/  backups/
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
from pathlib import Path

SITE_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?$")
APP_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class WorkspaceError(Exception):
    """A user-facing problem (bad name, missing site, ...). The CLI prints it without a traceback."""


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.apps_dir = self.root / "apps"
        self.sites_dir = self.root / "sites"

    # ---- creation / discovery -----------------------------------------------------------------
    @classmethod
    def create(cls, path: str | Path) -> "Workspace":
        from . import layout
        ws = cls(Path(path))
        if cls.is_workspace(ws.root):
            raise WorkspaceError(f"{ws.root} is already a Velora workspace")
        for d in (ws.apps_dir, ws.root / "config", ws.root / "logs", ws.root / "backups"):
            d.mkdir(parents=True, exist_ok=True)
        (ws.root / "config" / "apps.txt").write_text("")
        (ws.root / "config" / "common.json").write_text(json.dumps({"developer_mode": False}, indent=2) + "\n")
        layout.refresh_documents(ws)
        layout.secure(ws)
        return ws

    @staticmethod
    def is_workspace(root: str | Path) -> bool:
        """A folder is a workspace when it has config/apps.txt (or, in an older installation, sites/apps.txt)."""
        root = Path(root)
        return (root / "config" / "apps.txt").exists() or (root / "sites" / "apps.txt").exists()

    # ---- the three settings files: config/ now, sites/ in older installations until they are moved --------------------------
    def _settings_file(self, new: str, old: str) -> Path:
        n, o = self.root / "config" / new, self.sites_dir / old
        return o if (not n.exists() and o.exists()) else n

    @property
    def apps_file(self) -> Path:
        return self._settings_file("apps.txt", "apps.txt")

    @property
    def common_config_file(self) -> Path:
        return self._settings_file("common.json", "common_site_config.json")

    @property
    def events_file(self) -> Path:
        return self._settings_file("lifecycle.json", "lifecycle_log.json")

    @classmethod
    def discover(cls, start: str | Path | None = None) -> "Workspace | None":
        env = os.environ.get("VELORA_WORKSPACE")
        if env:
            ws = cls(Path(env))
            return ws if cls.is_workspace(ws.root) else None
        p = Path(start or Path.cwd()).resolve()
        for d in (p, *p.parents):
            if cls.is_workspace(d):
                return cls(d)
        return None

    # ---- apps ----------------------------------------------------------------------------------
    def apps(self) -> list[str]:
        f = self.apps_file
        return [l.strip() for l in f.read_text().splitlines() if l.strip()] if f.exists() else []

    def register_app(self, name: str):
        apps = self.apps()
        if name not in apps:
            f = self.apps_file
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("\n".join([*apps, name]) + "\n")

    def unregister_app(self, name: str):
        """Remove an app from the workspace code catalogue; does not delete its directory."""
        apps = [app for app in self.apps() if app != name]
        f = self.apps_file
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(chr(10).join(apps) + (chr(10) if apps else ""))

    def activate(self):
        """Put every workspace app on sys.path so installed apps are importable (like bench's virtualenv installs)."""
        for name in self.apps():
            p = str(self.apps_dir / name)
            if (self.apps_dir / name).is_dir() and p not in sys.path:
                sys.path.insert(0, p)
        importlib.invalidate_caches()

    def app_path(self, name: str) -> Path:
        return self.apps_dir / name

    # ---- sites ----------------------------------------------------------------------------------
    def site_path(self, name: str) -> Path:
        if not SITE_NAME_RE.match(name or "") or ".." in name:
            raise WorkspaceError(f"Invalid site name {name!r} (use lowercase letters, digits, dots and hyphens, e.g. erp.local)")
        return self.sites_dir / name

    def sites(self) -> list[str]:
        if not self.sites_dir.exists():
            return []
        return sorted(d.name for d in self.sites_dir.iterdir() if (d / "site_config.json").exists())

    def common_config(self) -> dict:
        f = self.common_config_file
        return json.loads(f.read_text()) if f.exists() else {}

    def update_config(self, **values) -> dict:
        """Merge keys into config/common.json (atomically). A key set to None is removed. Returns the new config."""
        cfg = self.common_config()
        for k, v in values.items():
            if v is None:
                cfg.pop(k, None)
            else:
                cfg[k] = v
        f = self.common_config_file
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.replace(tmp, f)
        return cfg

    def current_site(self, explicit: str | None = None) -> str:
        name = explicit or os.environ.get("VELORA_SITE")
        if not name:
            f = self.sites_dir / "currentsite.txt"
            if f.exists():
                name = f.read_text().strip()
        if not name:
            sites = self.sites()
            if len(sites) == 1:
                name = sites[0]
        if not name:
            raise WorkspaceError("No site selected. Use --site <name>, set VELORA_SITE, or run `velora use <site>`.")
        if name not in self.sites():
            raise WorkspaceError(f"Site {name!r} does not exist in {self.root}. Existing sites: {', '.join(self.sites()) or 'none'}")
        return name

    def use(self, name: str):
        if name not in self.sites():
            raise WorkspaceError(f"Site {name!r} does not exist")
        (self.sites_dir / "currentsite.txt").write_text(name + "\n")


def resolve_desk_path(ws: Workspace | None = None) -> str | None:
    """Where the built Desk UI lives: workspace config → env → packaged with velora → repo build."""
    cands = []
    if ws:
        cands.append(ws.common_config().get("desk_path"))
    cands += [os.environ.get("VELORA_FRONTEND_DIST"), str(Path(__file__).parent / "desk"),
              str(Path(__file__).resolve().parent.parent / "frontend" / "dist")]
    for c in cands:
        if c and (Path(c) / "index.html").exists():
            return str(c)
    return None
