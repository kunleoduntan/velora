from __future__ import annotations

import importlib
import sys

import pytest

from velora.app_runtime import _asset_entries, call_lifecycle_hook, inspect_app_extensions
from velora.exceptions import MetaError


def _package(tmp_path, monkeypatch, name="sample_ext"):
    root = tmp_path / name
    root.mkdir()
    (root / "__init__.py").write_text('__version__ = "1.2.3"\n')
    (root / "hooks.py").write_text(
        'frontend_assets = ["public/app.js", {"path": "public/app.css"}]\n'
        'events = []\n'
        'def before_install(): events.append("before_install")\n'
        'def after_migrate(): events.append("after_migrate")\n'
    )
    (root / "public").mkdir()
    (root / "public" / "app.js").write_text('window.sampleExtensionLoaded = true;\n')
    (root / "public" / "app.css").write_text('body { --sample-ext: 1; }\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    sys.modules.pop(name, None)
    sys.modules.pop(f"{name}.hooks", None)
    return name


def test_inspect_app_extension_manifest_and_lifecycle(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch)
    manifest = inspect_app_extensions(name)
    assert manifest["name"] == name
    assert manifest["version"] == "1.2.3"
    assert [x["type"] for x in manifest["frontend_assets"]] == ["javascript", "stylesheet"]
    assert all(len(x["sha256"]) == 64 and x["size_bytes"] > 0 for x in manifest["frontend_assets"])
    assert "before_install" in manifest["lifecycle_hooks"]
    call_lifecycle_hook(name, "before_install")
    call_lifecycle_hook(name, "after_migrate")
    hooks = importlib.import_module(f"{name}.hooks")
    assert hooks.events == ["before_install", "after_migrate"]


def test_frontend_asset_paths_are_restricted():
    with pytest.raises(MetaError):
        _asset_entries(type("Hooks", (), {"frontend_assets": ["../outside.js"]})())
    with pytest.raises(MetaError):
        _asset_entries(type("Hooks", (), {"frontend_assets": ["app.py"]})())
    with pytest.raises(MetaError):
        _asset_entries(type("Hooks", (), {"frontend_assets": "app.js"})())


def test_missing_frontend_asset_fails_closed(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch)
    (tmp_path / name / "public" / "app.js").unlink()
    with pytest.raises(MetaError):
        inspect_app_extensions(name)


def test_lifecycle_hook_supports_dotted_path(tmp_path, monkeypatch):
    name = _package(tmp_path, monkeypatch, "sample_dotted")
    hooks = importlib.import_module(f"{name}.hooks")
    hooks.before_install = f"{name}.setup.before_install"
    assert "before_install" in inspect_app_extensions(name)["lifecycle_hooks"]
    (tmp_path / name / "setup.py").write_text(
        'def before_install():\n    import builtins\n    builtins._velora_hook_marker = "called"\n'
    )
    call_lifecycle_hook(name, "before_install")
    import builtins
    assert builtins._velora_hook_marker == "called"
    del builtins._velora_hook_marker


def test_only_installed_app_declared_assets_resolve(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from velora.app_runtime import resolve_declared_asset
    from velora.meta.registry import Registry
    from velora import site as site_mod
    name = _package(tmp_path, monkeypatch, "sample_registry")
    site_registry = Registry()
    site_registry.load([name])
    monkeypatch.setattr(site_mod, "current", lambda: SimpleNamespace(registry=site_registry))
    asset, mime = resolve_declared_asset(name, "public/app.js")
    assert asset.name == "app.js" and mime in {"text/javascript", "application/javascript"}
    with pytest.raises(Exception, match="not declared"):
        resolve_declared_asset(name, "public/other.js")
