"""Run the ERP tests on PostgreSQL when VELORA_ERP_TEST_PG_URL is set (otherwise each test uses its own SQLite file).

With the variable set, every `velora.configure(db_url=...)` the tests make is pointed at that database, and the database is emptied
right after `velora.init()`, so every test starts from a clean slate exactly as it does on SQLite. Run serially (one process)."""
import os

import pytest

PG = os.environ.get("VELORA_ERP_TEST_PG_URL")


@pytest.fixture(autouse=True)
def _erp_tests_on_postgres(monkeypatch):
    if not PG:
        yield
        return
    import velora
    from velora import db
    real_configure, real_init = velora.configure, velora.init

    def configure(*args, **kwargs):
        if str(kwargs.get("db_url", "")).startswith("sqlite"):
            kwargs["db_url"] = PG
        return real_configure(*args, **kwargs)

    def init(*args, **kwargs):
        out = real_init(*args, **kwargs)
        from sqlalchemy import MetaData
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
        from velora.meta.registry import registry
        registry.load_company_doctypes([])
        return out

    monkeypatch.setattr(velora, "configure", configure)
    monkeypatch.setattr(velora, "init", init)
    yield
