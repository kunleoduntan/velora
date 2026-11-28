"""Every script report must at least build with empty filters (catches constructor/typing mistakes that only show when someone opens it)."""
import glob, importlib, json, os
import pytest
import velora
from velora.exceptions import VeloraError
from velora_erp.setup import after_install

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'rp.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _modules():
    for path in sorted(glob.glob(f"{ROOT}/velora_erp/**/report/*/*.json", recursive=True)):
        data = json.load(open(path))
        if data.get("type") != "script": continue
        rel = os.path.relpath(path[:-5] + ".py", ROOT).replace(os.sep, ".")[:-3]
        yield data["name"], rel


def test_every_script_report_builds_with_empty_filters(site):
    failures = []
    for name, module in _modules():
        try:
            out = importlib.import_module(module).execute({})
            if hasattr(out, "build"): out.build()
        except VeloraError:
            pass        # a required filter or a missing configuration is a clear message, not a crash
        except Exception as exc:                                  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not failures, "\n".join(failures)
