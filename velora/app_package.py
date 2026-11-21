"""Validation and deterministic distribution archives for Velora applications."""
from __future__ import annotations

import hashlib
import io
import json
import os
import ast
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib
import zipfile
from pathlib import Path, PurePosixPath

from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion

from .workspace import APP_NAME_RE, Workspace, WorkspaceError

EXCLUDED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "build", "dist", "*.egg-info"}
EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "site_config.json", "common_site_config.json"}
MAX_PACKAGE_BYTES = 100 * 1024 * 1024


def _app_root(ws: Workspace, name: str) -> Path:
    if not APP_NAME_RE.fullmatch(name or ""):
        raise WorkspaceError(f"Invalid app name {name!r}")
    root = ws.app_path(name).resolve()
    apps = ws.apps_dir.resolve()
    if root.parent != apps or not root.is_dir():
        raise WorkspaceError(f"App {name!r} is not present in this workspace")
    return root


def inspect_app(ws: Workspace, name: str) -> dict:
    """Validate an app package without importing or executing its Python code."""
    root = _app_root(ws, name)
    errors: list[str] = []
    warnings: list[str] = []
    project_file = root / "pyproject.toml"
    package_dir = root / name
    hooks_file = package_dir / "hooks.py"
    init_file = package_dir / "__init__.py"
    if not project_file.is_file():
        errors.append("Missing pyproject.toml")
        project = {}
    else:
        try:
            project = tomllib.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            errors.append(f"Invalid pyproject.toml: {exc}")
            project = {}
    meta = project.get("project", {}) if isinstance(project, dict) else {}
    if meta.get("name") != name:
        errors.append(f"pyproject.toml project.name must be {name!r}")
    try:
        version = Version(str(meta.get("version", "")))
    except InvalidVersion:
        version = None
        errors.append("pyproject.toml must declare a valid project.version")
    if not package_dir.is_dir() or not init_file.is_file():
        errors.append(f"Missing Python package directory {name}/__init__.py")
    if not hooks_file.is_file():
        warnings.append("No hooks.py found; lifecycle hooks and dependency declarations are unavailable")
    dependencies = meta.get("dependencies", []) or []
    if not isinstance(dependencies, list) or any(not isinstance(x, str) for x in dependencies):
        errors.append("project.dependencies must be an array of dependency strings")
        dependencies = []
    hook_values = {}
    if hooks_file.is_file():
        try:
            tree = ast.parse(hooks_file.read_text(encoding="utf-8"), filename=str(hooks_file))
            for node in tree.body:
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id in {"required_apps", "required_velora", "required_packages", "frontend_assets"}:
                            try:
                                hook_values[target.id] = ast.literal_eval(value)
                            except (ValueError, TypeError):
                                errors.append(f"hooks.py {target.id} must be a literal value")
        except (OSError, SyntaxError) as exc:
            errors.append(f"Invalid hooks.py: {exc}")
    frontend_assets = hook_values.get("frontend_assets", []) or []
    if not isinstance(frontend_assets, list):
        errors.append("hooks.py frontend_assets must be a literal array")
        frontend_assets = []
    for entry in frontend_assets:
        asset_path = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(asset_path, str) or not asset_path.strip():
            errors.append("Each frontend_assets entry must be a path or an object with path")
            continue
        rel = PurePosixPath(asset_path)
        if rel.is_absolute() or ".." in rel.parts or "\\" in asset_path or rel.suffix.lower() not in {".js", ".mjs", ".css"}:
            errors.append(f"Unsafe or unsupported frontend asset path: {asset_path!r}")
            continue
        raw_target = package_dir / Path(*rel.parts)
        target = raw_target.resolve()
        if raw_target.is_symlink() or not target.is_relative_to(package_dir.resolve()) or not target.is_file():
            errors.append(f"Frontend asset does not exist inside the app package: {asset_path!r}")
    required_apps = hook_values.get("required_apps", []) or []
    if not isinstance(required_apps, list) or any(not isinstance(x, str) or not APP_NAME_RE.fullmatch(x) for x in required_apps):
        errors.append("hooks.py required_apps must be an array of valid app names")
        required_apps = []
    required_velora = hook_values.get("required_velora", "") or ""
    if not isinstance(required_velora, str):
        errors.append("hooks.py required_velora must be a version specifier string")
        required_velora = ""
    elif required_velora:
        try:
            SpecifierSet(required_velora)
        except Exception:
            errors.append(f"Invalid hooks.py required_velora specifier: {required_velora!r}")
    files = []
    total = 0
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in rel.parts):
                continue
            if path.name in EXCLUDED_NAMES or path.name.startswith(".env.") or path.suffix in {".pyc", ".pyo", ".db", ".sqlite"}:
                continue
            if path.is_symlink():
                errors.append(f"Symbolic links are not allowed in app packages: {rel.as_posix()}")
                continue
            try:
                size = path.stat().st_size
            except OSError:
                errors.append(f"Cannot inspect file: {rel.as_posix()}")
                continue
            total += size
            files.append(rel.as_posix())
            if total > MAX_PACKAGE_BYTES:
                errors.append(f"App package exceeds the {MAX_PACKAGE_BYTES // (1024 * 1024)} MB limit")
                break
    # Validate DocType JSON without importing controllers.
    for rel in files:
        p = root / rel
        if p.suffix == ".json" and "doctype" in PurePosixPath(rel).parts:
            try:
                spec = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(spec, dict) or not spec.get("name"):
                    errors.append(f"DocType JSON must be an object with a name: {rel}")
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"Invalid DocType JSON {rel}: {exc}")
    return {
        "name": name,
        "version": str(version) if version else None,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "dependencies": dependencies,
        "required_apps": required_apps,
        "required_velora": required_velora,
        "file_count": len(files),
        "size_bytes": total,
        "files": files,
    }


def build_app_archive(ws: Workspace, name: str) -> tuple[bytes, dict]:
    report = inspect_app(ws, name)
    if not report["valid"]:
        raise WorkspaceError("App validation failed: " + "; ".join(report["errors"]))
    root = _app_root(ws, name)
    manifest = {
        "format": "velora-app-package",
        "format_version": 1,
        "name": name,
        "version": report["version"],
        "required_velora": report["required_velora"],
        "required_apps": report["required_apps"],
        "dependencies": report["dependencies"],
        "files": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for rel in report["files"]:
            data = (root / rel).read_bytes()
            archive.writestr(f"{name}/{rel}", data)
            manifest["files"].append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
        # Add a machine-readable manifest; do not overwrite a developer-owned file.
        archive.writestr(f"{name}/velora_app_manifest.json", json.dumps(manifest, indent=2) + "\n")
    return buffer.getvalue(), report


def validate_archive(data: bytes) -> dict:
    """Validate an uploaded package archive against traversal, symlink and manifest attacks."""
    if len(data) > MAX_PACKAGE_BYTES:
        raise WorkspaceError("Package exceeds the 100 MB upload limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if not names:
                raise WorkspaceError("Package archive is empty")
            if len(names) != len(set(names)):
                raise WorkspaceError("Package archive contains duplicate paths")
            if sum(i.file_size for i in archive.infolist()) > MAX_PACKAGE_BYTES:
                raise WorkspaceError("Expanded package exceeds the 100 MB limit")
            for info in archive.infolist():
                p = PurePosixPath(info.filename)
                if p.is_absolute() or ".." in p.parts or "\\" in info.filename:
                    raise WorkspaceError(f"Unsafe package path: {info.filename}")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise WorkspaceError(f"Symbolic links are not allowed: {info.filename}")
            manifests = [n for n in names if n.endswith("/velora_app_manifest.json")]
            if len(manifests) != 1:
                raise WorkspaceError("Package must contain exactly one velora_app_manifest.json")
            manifest = json.loads(archive.read(manifests[0]))
            if manifest.get("format") != "velora-app-package" or manifest.get("format_version") != 1:
                raise WorkspaceError("Unsupported Velora app package format")
            app = manifest.get("name")
            if not APP_NAME_RE.fullmatch(app or "") or not manifests[0].startswith(app + "/"):
                raise WorkspaceError("Package app name does not match its root directory")
            listed = {f.get("path"): f for f in manifest.get("files", [])}
            expected = {f"{app}/{rel}" for rel in listed} | {manifests[0]}
            actual_files = {n for n in names if not n.endswith("/")}
            if actual_files != expected:
                raise WorkspaceError("Package contains files not declared in its manifest, or is missing declared files")
            for rel, item in listed.items():
                full = f"{app}/{rel}"
                if full not in names:
                    raise WorkspaceError(f"Package manifest references missing file: {rel}")
                content = archive.read(full)
                if hashlib.sha256(content).hexdigest() != item.get("sha256") or len(content) != item.get("size"):
                    raise WorkspaceError(f"Package integrity check failed: {rel}")
            if not {f"{app}/pyproject.toml", f"{app}/{app}/__init__.py"}.issubset(names):
                raise WorkspaceError("Package is missing pyproject.toml or its Python package")
            try:
                Version(str(manifest.get("version", "")))
                SpecifierSet(str(manifest.get("required_velora", "") or ""))
            except Exception as exc:
                raise WorkspaceError(f"Invalid package version compatibility metadata: {exc}") from None
            required_apps = manifest.get("required_apps", [])
            if not isinstance(required_apps, list) or any(not isinstance(x, str) or not APP_NAME_RE.fullmatch(x) for x in required_apps):
                raise WorkspaceError("Package required_apps metadata is invalid")
            return {"valid": True, "name": app, "version": manifest.get("version"), "file_count": len(listed)}
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise WorkspaceError(f"Invalid Velora app package: {exc}") from None


def install_package(ws: Workspace, data: bytes, *, overwrite: bool = False) -> str:
    """Extract a validated app archive into workspace/apps; never installs it on a site."""
    report = validate_archive(data)
    name = report["name"]
    dest = ws.app_path(name)
    if dest.exists() and not overwrite:
        raise WorkspaceError(f"App {name!r} already exists; use overwrite explicitly to replace its source")
    staging = ws.apps_dir / f".{name}.staging"
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                p = PurePosixPath(info.filename)
                if len(p.parts) < 2 or p.parts[0] != name or info.is_dir():
                    continue
                target = staging.joinpath(*p.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        if dest.exists():
            import shutil
            backup = ws.apps_dir / f".{name}.previous"
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(dest, backup)
            try:
                os.replace(staging, dest)
            except Exception:
                os.replace(backup, dest)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.replace(staging, dest)
        ws.register_app(name)
        return name
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging, ignore_errors=True)
