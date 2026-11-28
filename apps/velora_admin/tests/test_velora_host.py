"""Velora Admin on a real Velora site beside VeloraERP: loads, installs, renames old tables."""
import json
import os

import pytest
from sqlalchemy import text

import velora
from velora import db, new_doc


@pytest.fixture()
def site(tmp_path):
    pg = os.environ.get("VELORA_ADMIN_TEST_PG_URL")
    velora.configure(db_url=pg or f"sqlite:///{tmp_path / 'adm.db'}", apps=["velora_erp", "velora_projectone", "velora_admin"], developer_mode=True)
    velora.init()
    if pg:
        from sqlalchemy import MetaData
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
    velora.migrate()
    yield
    velora.shutdown()


def test_doctypes_load_without_the_administrative_prefix(site):
    names = _doctypes()
    for new in ("Request", "Request Type", "Service", "Task", "Vendor", "Facility", "Trip", "Knowledge Article"):
        assert new in names
    for old in ("Administrative Request", "Administrative Task", "Administrative Vendor", "Administrative Service"):
        assert old not in names
    for kept in ("Administrative Vehicle", "Administrative Visitor", "Administrative Travel Request", "Administrative Event", "Administrative Correspondence"):
        assert kept in names                                  # the bare name already exists in this app, so the prefix stays


def test_the_upgrade_patch_renames_old_tables(site):
    from velora.db.tables import table_name
    from velora_admin.patches.v1_9 import drop_administrative_prefix as p
    old, new = table_name("Administrative Task"), table_name("Task")
    with db.transaction() as c:
        c.execute(text(f'ALTER TABLE "{new}" RENAME TO "{old}"'))
        c.execute(text(f"INSERT INTO \"{old}\" (name) VALUES ('T-1')"))
    p.execute()
    with db.transaction() as c:
        assert c.execute(text(f'SELECT name FROM "{new}"')).scalars().all() == ["T-1"]
    p.execute()                                                   # running again changes nothing


def _doctypes():
    from velora.meta.registry import registry
    return {m.name for m in registry.all()}
