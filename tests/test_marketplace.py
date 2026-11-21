import zipfile
from pathlib import Path

import pytest

from velora.marketplace import add_source, list_packages, remove_source, import_package
from velora.scaffold import new_app
from velora.app_package import build_app_archive
from velora.workspace import Workspace, WorkspaceError


def test_marketplace_source_add_list_remove(tmp_path):
    ws = Workspace.create(tmp_path / "workspace")
    repo = tmp_path / "repo"
    repo.mkdir()
    result = add_source(ws, "stable", repo)
    assert result["name"] == "stable"
    assert list_packages(ws)[0]["status"] == "available"
    remove_source(ws, "stable")
    assert list_packages(ws) == []


def test_marketplace_rejects_missing_repo_and_path_traversal(tmp_path):
    ws = Workspace.create(tmp_path / "workspace")
    with pytest.raises(WorkspaceError):
        add_source(ws, "bad", tmp_path / "missing")
    repo = tmp_path / "repo"
    repo.mkdir()
    add_source(ws, "stable", repo)
    with pytest.raises(WorkspaceError):
        import_package(ws, "stable", "../evil.zip")


def test_marketplace_lists_and_imports_a_validated_package(tmp_path):
    source = Workspace.create(tmp_path / "source")
    new_app(source.apps_dir, "fleet_ops", module="Fleet", title="Fleet Operations")
    source.register_app("fleet_ops")
    archive, _ = build_app_archive(source, "fleet_ops")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "fleet_ops-0.0.1.zip").write_bytes(archive)
    target = Workspace.create(tmp_path / "target")
    add_source(target, "stable", repo)
    package = list_packages(target)[0]["packages"][0]
    assert package["status"] == "valid"
    result = import_package(target, "stable", package["file"], package["sha256"])
    assert result["name"] == "fleet_ops"
    assert "fleet_ops" in target.apps()
