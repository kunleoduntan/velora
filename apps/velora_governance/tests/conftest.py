"""Some governance tests read packaged files (docs, page scripts) by relative path: run them from the package folder."""
import sys as _sys
from pathlib import Path as _Path
_ERP_TESTS = _Path(__file__).resolve().parents[2] / "velora_erp" / "tests"      # end-to-end tests reuse VeloraERP's fixtures when it is present
if _ERP_TESTS.is_dir() and str(_ERP_TESTS) not in _sys.path:
    _sys.path.append(str(_ERP_TESTS))

from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[1] / "velora_governance"


@pytest.fixture(autouse=True)
def _from_package_folder(monkeypatch):
    monkeypatch.chdir(PKG)
