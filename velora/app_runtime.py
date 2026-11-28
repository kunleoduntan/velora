"""Installed application runtime extensions.

App code is trusted, versioned package code. Company data and installed-app membership
remain site-local. Frontend assets are served only when declared by an installed app.
"""
from __future__ import annotations

import importlib
import mimetypes
import hashlib
from pathlib import Path, PurePosixPath

from .exceptions import MetaError
from .workspace import WorkspaceError

ASSET_TYPES = {".js": "javascript", ".mjs": "javascript", ".css": "stylesheet"}
LIFECYCLE_HOOKS = (
    "before_install", "after_install", "before_uninstall", "after_uninstall",
    "before_migrate", "after_migrate",
)


def _app_package(app: str):
    try:
        return importlib.import_module(app)
    except ImportError as exc:
        raise WorkspaceError(f"Application package {app!r} is not importable: {exc}") from None


def _asset_entries(hooks) -> list[dict]:
    raw = getattr(hooks, "frontend_assets", []) or []
    if not isinstance(raw, (list, tuple)):
        raise MetaError("hooks.py frontend_assets must be a list")
    out, seen = [], set()
    for entry in raw:
        if isinstance(entry, str):
            path = entry
        elif isinstance(entry, dict):
            path = entry.get("path")
        else:
            raise MetaError("Each frontend_assets entry must be a path or an object with path")
        if not isinstance(path, str) or not path.strip():
            raise MetaError("frontend_assets paths must be non-empty strings")
        rel = PurePosixPath(path)
        if rel.is_absolute() or ".." in rel.parts or "\\" in path or not rel.parts:
            raise MetaError(f"Unsafe frontend asset path: {path!r}")
        suffix = rel.suffix.lower()
        if suffix not in ASSET_TYPES:
            raise MetaError(f"Unsupported frontend asset type for {path!r}; use .js, .mjs or .css")
        normalized = rel.as_posix()
        if normalized in seen:
            raise MetaError(f"Duplicate frontend asset: {normalized}")
        seen.add(normalized)
        out.append({"path": normalized, "type": ASSET_TYPES[suffix]})
    return out


def inspect_app_extensions(app: str) -> dict:
    package = _app_package(app)
    try:
        hooks = importlib.import_module(f"{app}.hooks")
    except ModuleNotFoundError as exc:
        if exc.name != f"{app}.hooks":
            raise
        hooks = None
    assets = _asset_entries(hooks) if hooks else []
    declared_lifecycle = []
    if hooks:
        for hook_name in LIFECYCLE_HOOKS:
            value = getattr(hooks, hook_name, None)
            if value is None:
                continue
            if callable(value):
                declared_lifecycle.append(hook_name)
            elif isinstance(value, str) and "." in value and all(part.isidentifier() for part in value.split(".")):
                declared_lifecycle.append(hook_name)
            else:
                raise MetaError(f"{app}.hooks.{hook_name} must be a callable, dotted function path or None")
    root = Path(package.__file__).resolve().parent
    for asset in assets:
        raw_target = root / asset["path"]
        target = raw_target.resolve()
        if raw_target.is_symlink() or not target.is_relative_to(root) or not target.is_file():
            raise MetaError(f"Frontend asset {asset['path']!r} must be an existing regular file inside the app package")
    asset_inventory = []
    for asset in assets:
        target = (root / asset["path"]).resolve()
        content = target.read_bytes()
        asset_inventory.append({**asset, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
    return {
        "name": app,
        "version": str(getattr(package, "__version__", "0.0.0")),
        "frontend_assets": asset_inventory,
        "lifecycle_hooks": declared_lifecycle,
        "doc_events": bool(hooks and getattr(hooks, "doc_events", None)),
        "scheduler_events": sorted((getattr(hooks, "scheduler_events", {}) or {}).keys()) if hooks else [],
        "job_handlers": sorted((getattr(hooks, "job_handlers", {}) or {}).keys()) if hooks and isinstance(getattr(hooks, "job_handlers", None), dict) else [],
    }


def resolve_declared_asset(app: str, asset_path: str) -> tuple[Path, str]:
    """Resolve only an asset explicitly declared by an installed app's hooks.py."""
    from .meta.registry import registry
    if app not in registry.apps:
        raise WorkspaceError(f"Application {app!r} is not installed on this company")
    manifest = inspect_app_extensions(app)
    match = next((a for a in manifest["frontend_assets"] if a["path"] == asset_path), None)
    if not match:
        raise WorkspaceError("Asset is not declared by this installed application")
    package = _app_package(app)
    root = Path(package.__file__).resolve().parent
    raw_target = root / asset_path
    target = raw_target.resolve()
    if raw_target.is_symlink() or not target.is_relative_to(root) or not target.is_file():
        raise WorkspaceError("Application asset path is invalid")
    mime = mimetypes.guess_type(target.name)[0] or ("text/css" if match["type"] == "stylesheet" else "text/javascript")
    return target, mime


def call_lifecycle_hook(app: str, hook_name: str) -> None:
    if hook_name not in LIFECYCLE_HOOKS:
        raise ValueError(f"Unsupported application lifecycle hook: {hook_name}")
    try:
        hooks = importlib.import_module(f"{app}.hooks")
    except ModuleNotFoundError as exc:
        if exc.name == f"{app}.hooks":
            return
        raise
    fn = getattr(hooks, hook_name, None)
    if fn is None:
        return
    if isinstance(fn, str):
        module, separator, attr = fn.rpartition(".")
        if not separator or not module or not attr:
            raise MetaError(f"{app}.hooks.{hook_name} must be a callable or dotted function path")
        fn = getattr(importlib.import_module(module), attr, None)
    if not callable(fn):
        raise MetaError(f"{app}.hooks.{hook_name} must resolve to a callable")
    fn()
