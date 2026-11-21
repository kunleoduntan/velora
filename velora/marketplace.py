"""Local, content-addressed catalogue for distributable Velora application packages.

Repositories are local directories. Packages are validated without importing or executing
their Python code; installing into a workspace is separate from installing on a company.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .app_package import validate_archive, install_package
from .workspace import Workspace, WorkspaceError

SOURCE_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _sources(ws: Workspace) -> dict:
    raw = ws.common_config().get("marketplace_sources", {})
    if not isinstance(raw, dict):
        raise WorkspaceError("marketplace_sources configuration must be an object")
    return raw


def add_source(ws: Workspace, name: str, path: str | Path) -> dict:
    if not SOURCE_RE.fullmatch(name or ""):
        raise WorkspaceError("Repository name must use lowercase letters, digits and underscores")
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise WorkspaceError(f"Marketplace repository directory does not exist: {folder}")
    sources = _sources(ws)
    sources[name] = str(folder)
    ws.update_config(marketplace_sources=sources)
    return {"name": name, "path": str(folder)}


def remove_source(ws: Workspace, name: str) -> None:
    sources = _sources(ws)
    if name not in sources:
        raise WorkspaceError(f"Unknown marketplace repository: {name}")
    sources.pop(name)
    ws.update_config(marketplace_sources=sources or None)


def list_packages(ws: Workspace) -> list[dict]:
    rows = []
    for repo, raw_path in sorted(_sources(ws).items()):
        folder = Path(raw_path).expanduser().resolve()
        if not folder.is_dir():
            rows.append({"repository": repo, "status": "unavailable", "path": str(folder), "packages": []})
            continue
        packages = []
        for archive in sorted(folder.glob("*.zip")):
            try:
                data = archive.read_bytes()
                info = validate_archive(data)
                packages.append({
                    **info, "file": archive.name, "path": str(archive),
                    "sha256": hashlib.sha256(data).hexdigest(), "status": "valid",
                })
            except Exception as exc:
                packages.append({"file": archive.name, "path": str(archive), "status": "invalid", "error": str(exc)})
        rows.append({"repository": repo, "status": "available", "path": str(folder), "packages": packages})
    return rows


def import_package(ws: Workspace, repository: str, filename: str, expected_sha256: str | None = None, overwrite: bool = False) -> dict:
    if Path(filename).name != filename or not filename.endswith(".zip"):
        raise WorkspaceError("Package filename must be a ZIP file name, not a path")
    sources = _sources(ws)
    if repository not in sources:
        raise WorkspaceError(f"Unknown marketplace repository: {repository}")
    folder = Path(sources[repository]).expanduser().resolve()
    archive = (folder / filename).resolve()
    if not archive.is_relative_to(folder) or not archive.is_file():
        raise WorkspaceError("Package file is not present in the selected repository")
    data = archive.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise WorkspaceError("Package SHA-256 does not match the expected digest")
    info = validate_archive(data)
    name = install_package(ws, data, overwrite=overwrite)
    return {"name": name, "version": info["version"], "sha256": digest, "workspace_only": True,
            "message": "Application source added to this workspace. It has not been installed on any company."}
