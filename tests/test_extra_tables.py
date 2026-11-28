"""Engine tables (print formats, jobs, scripts, dashboards, files, workflows, website, portal, integrations) belong to the migration, not to a request."""
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import velora
from velora import db, printing
from velora.controlplane import ControlPlane
from velora.db import extra_tables
from velora.db.schema import migrate
from velora.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent


def existing():
    return set(inspect(db.get_engine()).get_table_names())


def names():
    return {t.name for t in extra_tables.tables()}


# ============================== nothing can be forgotten ==============================
def test_every_engine_module_that_owns_tables_is_registered():
    """A new engine that defines its own MetaData but is not listed in OWNERS would go back to creating tables during a request. This fails first."""
    owners = {m for m, _ in extra_tables.OWNERS}
    found = set()
    for f in (ROOT / "velora").rglob("*.py"):
        rel = f.relative_to(ROOT).with_suffix("")
        mod = ".".join(rel.parts)
        if mod.startswith(("velora.db.", "velora.controlplane")) or mod in ("velora.db.system",):
            continue                                                                                 # system tables and the control plane have their own migration
        if re.search(r"^\s*(?:md|_meta|\w*metadata)\s*=\s*MetaData\(", f.read_text(), re.M):
            found.add(mod)
    assert found - {"velora.layout"} == owners, (found ^ owners)


def test_the_tables_are_unique_prefixed_and_numerous_enough_to_matter():
    ts = [t.name for t in extra_tables.tables()]
    assert len(ts) == len(set(ts)) >= 31 and all(n.startswith("vl_") for n in ts)
    assert {"vl_background_job", "vl_file", "vl_workflow_definition", "vl_web_page", "vl_print_format", "vl_custom_script", "vl_webhook_queue", "vl_portal_user"} <= set(ts)


# ============================== the migration owns them ==============================
def test_a_migrated_database_has_every_engine_table_without_anything_having_run_a_request(site):
    assert names() <= existing()


def test_the_upgrade_plan_shows_a_missing_engine_table_and_creates_it_only_when_not_a_dry_run(site):
    with db.transaction() as c:
        c.execute(text("DROP TABLE vl_web_page"))
        c.execute(text("DROP TABLE vl_print_format"))
    plan = migrate(dry_run=True)
    assert any("vl_web_page" in line for line in plan) and any("vl_print_format" in line for line in plan)       # visible in the dry-run plan (it never was)
    assert {"vl_web_page", "vl_print_format"}.isdisjoint(existing())                                             # a dry run changes nothing
    migrate()
    assert {"vl_web_page", "vl_print_format"} <= existing() and migrate() == []                                  # created, and then there is nothing more to do


def test_an_upgrade_adds_a_new_column_to_an_engine_table(site):
    """What a later release's new column will look like on an existing installation: the table exists, the column does not."""
    with db.transaction() as c:
        c.execute(text("ALTER TABLE vl_web_page DROP COLUMN summary"))
    assert "summary" not in {col["name"] for col in inspect(db.get_engine()).get_columns("vl_web_page")}
    plan = migrate(dry_run=True)
    assert any("summary" in line for line in plan)
    migrate()
    assert "summary" in {col["name"] for col in inspect(db.get_engine()).get_columns("vl_web_page")}              # before this, an engine table could never gain a column


def test_a_new_company_gets_all_of_them_when_it_is_created(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    plane = ControlPlane.create(Workspace.create(tmp_path / "erp"), admin_email="boss@acme.ng", admin_password="a long passphrase 1")
    try:
        plane.registry.create_tenant("Acme Group")
        co = plane.provisioning.provision_company("Acme Group", "Acme Ltd", apps=[])
        with plane.company_scope(co["id"]):
            assert names() <= existing()
    finally:
        plane.dispose()


# ============================== the safety net is cheap and honest ==============================
def counted(monkeypatch):
    from sqlalchemy import MetaData
    calls = []
    real = MetaData.create_all
    monkeypatch.setattr(MetaData, "create_all", lambda self, bind=None, **kw: (calls.append(1), real(self, bind, **kw))[1])
    return calls


def test_ensure_runs_once_per_engine_not_on_every_call(site, monkeypatch):
    extra_tables._ensured.clear()
    calls = counted(monkeypatch)
    for _ in range(6):
        printing.ensure()
    assert len(calls) == 1                                                                                       # (several modules used to run a catalog query on every call)


def test_a_rolled_back_transaction_does_not_make_ensure_believe_the_table_exists(site, monkeypatch):
    """PostgreSQL DDL is part of the transaction: if the request that created a table rolls back, the table is gone and must be created again."""
    extra_tables._ensured.clear()
    calls = counted(monkeypatch)
    with pytest.raises(RuntimeError):
        with db.transaction():
            printing.ensure()
            raise RuntimeError("the request failed")
    printing.ensure()
    assert len(calls) == 2                                                                                       # the failed request did not mark it known
    with db.transaction():
        printing.ensure()
    printing.ensure()
    assert len(calls) == 2 or len(calls) == 3                                                                    # a committed one does (the second call inside the transaction found it known already)
    n = len(calls)
    printing.ensure()
    assert len(calls) == n


def test_the_safety_net_still_creates_a_table_in_a_database_that_was_never_migrated(site):
    with db.transaction() as c:
        c.execute(text("DROP TABLE vl_web_page"))
    extra_tables._ensured.clear()
    from velora import website
    website.ensure()
    assert "vl_web_page" in existing()                                                                           # a library session or a test without `velora migrate` still works
