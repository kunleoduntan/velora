"""Which PostgreSQL administrator login Velora uses to create and drop company databases.

Creating a company from the Desk must not ask for a password the installer already set up. The login is found, in this order:
  1. what the caller passed explicitly (the CLI flags / a password typed in the Desk);
  2. the environment: VELORA_DB_ROOT_USER, VELORA_DB_ROOT_PASSWORD;
  3. `pg_admin` in config/common.json: {"user": "velora_root", "password_file": "/srv/velora/.db-root-password"} (set with `velora pg admin set`; never a plain password);
  4. the installer's layout: `<install folder>/.db-root-password` next to the workspace, with the user `velora_root`.
The password itself is never stored in the workspace, never logged and never returned by the API.
"""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePath

DEFAULT_USER = "velora_root"
INSTALLER_FILE = ".db-root-password"


def _root(workspace) -> Path:
    """A Workspace object or a plain path (note: a Path itself has a `.root` attribute, so test the type, not hasattr)."""
    return Path(workspace) if isinstance(workspace, (str, PurePath)) else Path(workspace.root)


def _read(path) -> str | None:
    try:
        text = Path(path).read_text().strip()
        return text or None
    except OSError:
        return None


def _config(workspace) -> dict:
    try:
        return (json.loads((_root(workspace) / "config" / "common.json").read_text()) or {}).get("pg_admin") or {}
    except (OSError, ValueError):
        return {}


def resolve(workspace, root_user: str | None = None, root_password: str | None = None) -> tuple[str, str | None, str]:
    """(user, password, where it came from). The password is None when nothing is configured."""
    cfg = _config(workspace)
    root = _root(workspace)
    user = root_user or os.environ.get("VELORA_DB_ROOT_USER") or cfg.get("user")
    if root_password:
        return user or "postgres", root_password, "given"
    if os.environ.get("VELORA_DB_ROOT_PASSWORD"):
        return user or DEFAULT_USER, os.environ["VELORA_DB_ROOT_PASSWORD"], "environment"
    if cfg.get("password_file") and (pw := _read(cfg["password_file"])):
        return user or DEFAULT_USER, pw, "config"
    if pw := _read(root.parent / INSTALLER_FILE):
        return user or DEFAULT_USER, pw, "installer"
    return user or "postgres", None, "none"


def status(workspace) -> dict:
    """What the Desk may show: whether a login is available and its user name. Never the password."""
    user, pw, where = resolve(workspace)
    return {"configured": pw is not None, "user": user, "source": where}


def save(workspace, user: str, password_file: str) -> None:
    """Remember the login in config/common.json (the password stays in its file)."""
    if not user or not password_file:
        raise ValueError("a user and a password file are required")
    if _read(password_file) is None:
        raise ValueError(f"cannot read a password from {password_file}")
    root = _root(workspace)
    f = root / "config" / "common.json"
    try:
        data = json.loads(f.read_text()) or {}
    except (OSError, ValueError):
        data = {}
    data["pg_admin"] = {"user": user, "password_file": str(password_file)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2) + "\n")
