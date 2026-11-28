import json
from pathlib import Path

from velora.platform_readiness import (build_deployment_manifest, readiness_report,
    verify_deployment_manifest, write_deployment_manifest)
from velora.workspace import Workspace


def make_workspace(tmp_path):
    ws = Workspace.create(tmp_path / "workspace")
    (ws.apps_dir / "shop" / "shop").mkdir(parents=True)
    (ws.apps_dir / "shop" / "shop" / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (ws.apps_dir / "shop" / "pyproject.toml").write_text('[project]\nname="shop"\nversion="1.2.3"\n')
    ws.register_app("shop")
    site = ws.site_path("demo.local")
    site.mkdir(parents=True)
    (site / "site_config.json").write_text(json.dumps({"db_type": "sqlite", "db_name": "site.db", "secret_key": "not-in-manifest"}))
    return ws


def test_readiness_report_checks_structure_and_site_database_config(tmp_path):
    ws = make_workspace(tmp_path)
    report = readiness_report(ws, min_free_bytes=1)
    assert report["overall"] in ("ready", "warning")
    assert any(x["check"] == "site:demo.local:database_config" and x["status"] == "ok" for x in report["checks"])
    assert report["summary"]["fail"] == 0


def test_readiness_report_fails_on_invalid_site_config(tmp_path):
    ws = make_workspace(tmp_path)
    (ws.site_path("demo.local") / "site_config.json").write_text("{broken")
    report = readiness_report(ws)
    assert report["overall"] == "fail"
    assert any(x["check"] == "site:demo.local:config" and x["status"] == "fail" for x in report["checks"])


def test_manifest_excludes_secrets_and_detects_source_changes(tmp_path):
    ws = make_workspace(tmp_path)
    manifest = build_deployment_manifest(ws)
    serialized = json.dumps(manifest)
    assert "not-in-manifest" not in serialized
    assert all("site_config" not in f["path"] for f in manifest["files"])
    path = write_deployment_manifest(ws)
    result = verify_deployment_manifest(ws, path)
    assert result["valid"] and result["checked"] == len(manifest["files"])
    (ws.apps_dir / "shop" / "shop" / "__init__.py").write_text('__version__ = "1.2.4"\n')
    result = verify_deployment_manifest(ws, path)
    assert not result["valid"] and "apps/shop/shop/__init__.py" in result["changed"]


def test_manifest_rejects_path_traversal(tmp_path):
    ws = make_workspace(tmp_path)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"format": "velora-deployment-manifest", "format_version": 1,
                                "files": [{"path": "../outside", "sha256": "x", "size": 1}]}))
    import pytest
    from velora.workspace import WorkspaceError
    with pytest.raises(WorkspaceError, match="Unsafe manifest path"):
        verify_deployment_manifest(ws, path)


def test_cli_readiness_and_manifest_commands(tmp_path, capsys):
    from velora.cli import main
    ws = make_workspace(tmp_path)
    assert main(["--workspace", str(ws.root), "readiness"]) == 0
    assert '"overall"' in capsys.readouterr().out
    assert main(["--workspace", str(ws.root), "manifest", "create"]) == 0
    capsys.readouterr()
    assert main(["--workspace", str(ws.root), "manifest", "verify"]) == 0
    assert '"valid": true' in capsys.readouterr().out


def test_manifest_verifier_rejects_symlink_escape(tmp_path):
    import pytest
    from velora.workspace import WorkspaceError
    ws = make_workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = ws.root / "apps" / "shop" / "outside-link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"format": "velora-deployment-manifest", "format_version": 1,
                                "files": [{"path": "apps/shop/outside-link", "sha256": "x", "size": 6}]}))
    with pytest.raises(WorkspaceError, match="symlink"):
        verify_deployment_manifest(ws, path)
