import os
import sys
import tempfile

import pytest

import velora
from velora import db


def _db_urls():
    urls = [("sqlite", None)]
    if os.environ.get("VELORA_TEST_PG_URL"):
        urls.append(("postgres", os.environ["VELORA_TEST_PG_URL"]))
    return urls


@pytest.fixture(params=[p[0] for p in _db_urls()])
def site(request, tmp_path):
    """A fresh, fully migrated database per test, on every configured backend."""
    if request.param == "sqlite":
        url = f"sqlite:///{tmp_path / 'test.db'}"
    else:
        url = os.environ["VELORA_TEST_PG_URL"]
    cfg = velora.configure(db_url=url, apps=["velora_demo"], developer_mode=True)
    velora.init(cfg)
    # clean slate (PostgreSQL DB is shared between tests)
    with db.transaction() as conn:
        from sqlalchemy import MetaData
        md = MetaData()
        md.reflect(conn)
        md.drop_all(conn)
    from velora.meta.registry import registry
    registry.load_company_doctypes([])                       # the wipe removed the stored objects; do not keep the previous test's in memory
    velora.migrate()
    yield cfg
    velora.shutdown()


@pytest.fixture(autouse=True)
def _tests_never_leak_modules_or_sites(tmp_path_factory):
    """A test that activates a temporary workspace (the CLI does) puts its apps on sys.path and in sys.modules. Left behind, an empty `shop` from one test hides the real `shop` of
    the next test FILE (9 platform tests failed only when run after another file). Restore the import state and drop loaded sites after every test, whatever it did."""
    before_path, before_mods = list(sys.path), set(sys.modules)
    yield
    base = str(tmp_path_factory.getbasetemp())
    sys.path[:] = before_path
    for name in set(sys.modules) - before_mods:
        mod = sys.modules.get(name)
        where = (getattr(mod, "__file__", None) or "") + str(getattr(mod, "__path__", ""))
        if base in where:
            sys.modules.pop(name, None)
    try:
        from velora import site as site_mod
        site_mod.unload_all()
    except Exception:  # noqa: BLE001 - cleaning up must never fail a test
        pass
