"""The wheel is what customers install: every runtime data file must be inside it (a missing file only fails after `pip install`)."""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    src = out / "src"
    # build from a CLEAN COPY: a stale build/ directory in the repo would silently include files the packaging config forgot
    shutil.copytree(ROOT, src, ignore=shutil.ignore_patterns("node_modules", "build", "*.egg-info", ".git", "frontend", "__pycache__", ".pytest_cache", "*.db"))
    proc = subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "--no-build-isolation", "-q", "-w", str(out)],
                          cwd=src, capture_output=True, text=True, timeout=300)
    files = list(out.glob("velora-*.whl"))
    if proc.returncode or not files:
        pytest.skip(f"could not build a wheel here: {proc.stderr.strip()[:200]}")
    return zipfile.ZipFile(files[0]).namelist()


def test_runtime_data_files_are_in_the_wheel(wheel):
    for f in ("velora_notify/hooks.py", "velora_notify/notify/doctype/notification_rule/notification_rule.json", "velora_notify/notify/doctype/notification_delivery/notification_delivery.json",
              "velora_notify/patches.txt"):
        assert f in wheel, f                                           # the bundled notifications app must be IN the wheel, DocType JSON included
    assert "velora/patches.txt" in wheel                      # read by `velora upgrade`: missing = every upgrade fails
    assert "velora/theme/presets.json" in wheel            # read at import time by the theme engine: missing = nothing starts
    for must in ("velora/__init__.py", "velora/theme/engine.py", "velora/reporting/excel.py", "velora/cli.py"):
        assert must in wheel, must


def test_wheel_is_clean(wheel):
    assert not [n for n in wheel if n.startswith(("tests/", "apps/", "frontend/", "docs/"))]
    assert not [n for n in wheel if "__pycache__" in n or n.endswith(".pyc")]


def test_every_python_package_directory_is_shipped(wheel):
    """A new sub-package without __init__.py would silently be left out of the wheel."""
    shipped = {n.rsplit("/", 1)[0] for n in wheel if n.endswith(".py")}
    for init in (ROOT / "velora").rglob("__init__.py"):
        assert str(init.parent.relative_to(ROOT)).replace("\\", "/") in shipped
    for d in (ROOT / "velora").rglob("*"):
        if d.is_dir() and any(p.suffix == ".py" for p in d.iterdir()) and "desk" not in d.parts and "__pycache__" not in d.parts:
            assert (d / "__init__.py").exists(), f"{d} has Python files but no __init__.py (it would be dropped from the wheel)"
