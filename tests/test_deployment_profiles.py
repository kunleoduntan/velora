from pathlib import Path

import pytest

from velora.deployment import create_profile, list_profiles
from velora.workspace import Workspace, WorkspaceError


def _app(ws, name="sample_app"):
    ws.app_path(name).mkdir(parents=True)
    (ws.app_path(name) / name).mkdir()
    (ws.app_path(name) / f"{name}/__init__.py").write_text('__version__ = "1.0.0"\\n')
    ws.register_app(name)


def test_deployment_profile_create_and_list(tmp_path):
    control = Workspace.create(tmp_path / "control")
    source = Workspace.create(tmp_path / "source")
    target = Workspace.create(tmp_path / "target")
    _app(source)
    profile = create_profile(control, "staging_to_prod", str(source.root), str(target.root), ["sample_app"])
    assert profile["apps"] == ["sample_app"]
    assert list_profiles(control)[0]["name"] == "staging_to_prod"


def test_deployment_profile_refuses_same_workspace_and_unknown_app(tmp_path):
    control = Workspace.create(tmp_path / "control")
    source = Workspace.create(tmp_path / "source")
    _app(source)
    with pytest.raises(WorkspaceError):
        create_profile(control, "same", str(source.root), str(source.root), ["sample_app"])
    target = Workspace.create(tmp_path / "target")
    with pytest.raises(WorkspaceError):
        create_profile(control, "unknown", str(source.root), str(target.root), ["missing"])
