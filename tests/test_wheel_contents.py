"""A built wheel must carry every file the app reads at run time (a missing data file fails silently on a server installed from wheels)."""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = (".json", ".html", ".js", ".css", ".txt")


@pytest.mark.parametrize("project,package", [(".", "velora"), ("apps/velora_erp", "velora_erp")])
def test_the_wheel_contains_every_data_file_of_the_package(tmp_path, project, package):
    r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "-q", "-w", str(tmp_path), str(ROOT / project)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode:
        pytest.skip("cannot build wheels here: " + r.stderr.strip()[-200:])
    whl = next(tmp_path.glob(f"{package}-*.whl"))
    inside = set(zipfile.ZipFile(whl).namelist())
    base = ROOT / project
    pkg_dir = base / package
    wanted = {str(p.relative_to(base)) for p in pkg_dir.rglob("*") if p.is_file() and p.suffix in DATA and "__pycache__" not in p.parts
              and "tests" not in p.parts}
    missing = sorted(wanted - inside)
    assert not missing, f"{len(missing)} file(s) are not packaged: {missing[:10]}"
    if package == "velora":
        assert "velora/__main__.py" in inside and "velora/cli.py" in inside
