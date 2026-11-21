import io
import json
import zipfile

import pytest

from velora.app_package import build_app_archive, inspect_app, install_package, validate_archive
from velora.scaffold import new_app
from velora.workspace import Workspace, WorkspaceError


def _workspace(path):
    ws = Workspace.create(path)
    new_app(ws.apps_dir, "fleet_ops", module="Fleet", title="Fleet Operations")
    ws.register_app("fleet_ops")
    return ws


def test_app_validation_and_distribution_round_trip(tmp_path):
    source = _workspace(tmp_path / "source")
    report = inspect_app(source, "fleet_ops")
    assert report["valid"] is True
    archive, package_report = build_app_archive(source, "fleet_ops")
    assert package_report["version"] == "0.0.1"
    checked = validate_archive(archive)
    assert checked == {"valid": True, "name": "fleet_ops", "version": "0.0.1", "file_count": package_report["file_count"]}

    target = Workspace.create(tmp_path / "target")
    assert install_package(target, archive) == "fleet_ops"
    assert "fleet_ops" in target.apps()
    assert (target.app_path("fleet_ops") / "fleet_ops" / "hooks.py").is_file()
    assert "fleet_ops" not in target.apps() or (target.app_path("fleet_ops") / "fleet_ops" / "hooks.py").exists()


def test_package_integrity_detects_tampered_file(tmp_path):
    source = _workspace(tmp_path / "source")
    archive, _ = build_app_archive(source, "fleet_ops")
    src = zipfile.ZipFile(io.BytesIO(archive))
    entries = {n: src.read(n) for n in src.namelist()}
    entries["fleet_ops/README.md"] = b"tampered"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    with pytest.raises(WorkspaceError, match="integrity"):
        validate_archive(out.getvalue())


def test_package_rejects_path_traversal():
    out = io.BytesIO()
    manifest = {"format": "velora-app-package", "format_version": 1, "name": "fleet_ops", "version": "0.0.1", "files": []}
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("../escape", "bad")
        z.writestr("fleet_ops/velora_app_manifest.json", json.dumps(manifest))
        z.writestr("fleet_ops/pyproject.toml", '[project]\nname="fleet_ops"\nversion="0.0.1"')
        z.writestr("fleet_ops/fleet_ops/__init__.py", "")
    with pytest.raises(WorkspaceError, match="Unsafe package path"):
        validate_archive(out.getvalue())


def test_invalid_app_is_not_packaged(tmp_path):
    ws = _workspace(tmp_path / "source")
    (ws.app_path("fleet_ops") / "pyproject.toml").write_text("not valid toml = [")
    assert inspect_app(ws, "fleet_ops")["valid"] is False
    with pytest.raises(WorkspaceError, match="validation failed"):
        build_app_archive(ws, "fleet_ops")


def test_declared_frontend_assets_are_validated_and_packaged(tmp_path):
    source = _workspace(tmp_path / "source")
    app_root = source.app_path("fleet_ops") / "fleet_ops"
    (app_root / "public").mkdir()
    (app_root / "public" / "bundle.js").write_text("window.fleetReady = true;")
    hooks = app_root / "hooks.py"
    hooks.write_text('frontend_assets = ["public/bundle.js"]\n')
    report = inspect_app(source, "fleet_ops")
    assert report["valid"] is True
    archive, _ = build_app_archive(source, "fleet_ops")
    assert validate_archive(archive)["valid"] is True


def test_declared_frontend_asset_rejects_parent_traversal(tmp_path):
    source = _workspace(tmp_path / "source")
    hooks = source.app_path("fleet_ops") / "fleet_ops" / "hooks.py"
    hooks.write_text('frontend_assets = ["../secret.js"]\n')
    report = inspect_app(source, "fleet_ops")
    assert report["valid"] is False
    assert any("frontend asset path" in e.lower() for e in report["errors"])
