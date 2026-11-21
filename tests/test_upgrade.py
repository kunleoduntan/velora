import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

import velora
from velora import db, provision, site as site_mod
from velora.api import create_app
from velora.cli import main
from velora.controlplane import ControlPlane, models as cpm
from velora.db import schema
from velora.exceptions import PatchError
from velora.settings import get_setting, set_setting
from velora.upgrade import backup as bk, maintenance, patches, state, versions
from velora.upgrade.engine import UpgradeEngine, UpgradeError, collect_targets, inspect_target, upgrade_lock
from velora.workspace import Workspace, WorkspaceError

from upgrade_helpers import FAIL_ON_B_PATCH, OK_PATCH, OLD, PW, change_app, clean_modules, fresh_process, make_app

PG_ROOT_PW = os.environ.get("VELORA_TEST_PG_ROOT_PASSWORD")
H = {"X-Velora-Request": "1"}


@pytest.fixture(autouse=True)
def isolate(tmp_path):
    before_path, before_mods = list(sys.path), set(sys.modules)
    cwd = os.getcwd()
    yield
    os.chdir(cwd)
    clean_modules(tmp_path, before_path, before_mods)


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE"):
        monkeypatch.delenv(k, raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("Group")
    A = plane.provisioning.provision_company("Group", "Company A", apps=["shop"])
    B = plane.provisioning.provision_company("Group", "Company B", apps=["shop"])
    for cid in (A["id"], B["id"]):
        with plane.company_scope(cid):
            velora.new_doc("Product", title="Widget").insert()
    ns = type("NS", (), {})()
    ns.ws, ns.plane, ns.A, ns.B = ws, plane, A["id"], B["id"]
    ns.engine = lambda **kw: UpgradeEngine(ws, log=lambda m: None, **kw)
    yield ns
    plane.dispose()


def make_old(env, ids=None, cp=True):
    """Pretend the databases were last upgraded by an older release."""
    for cid in ids or (env.A, env.B):
        with env.plane.company_scope(cid) as site:
            set_setting("framework_version", OLD)
            site.gate_cache = None
    if cp:
        with env.plane.engine.begin() as c:
            c.execute(cpm.meta.update().where(cpm.meta.c.key == "schema_version").values(value=OLD))
        env.plane._gate = None


def titles(env, cid):
    with env.plane.company_scope(cid):
        return [d["title"] for d in velora.get_list("Product", fields=["title"], order_by="name asc")]


def columns(env, cid):
    with env.plane.company_scope(cid) as site:
        return {c["name"] for c in inspect(site.engine).get_columns("tab_product")}


# ============================== versions + the gate ==============================
def test_gate_rules():
    g = state.gate_state
    assert g("0.8.0", "0.8.0")[0] == "ok" and g("0.8.0", "0.8.7")[0] == "ok"             # bug-fix releases never need a data upgrade
    assert g("0.7.4", "0.8.0")[0] == "upgrade_pending" and g("0.9.9", "1.0.0")[0] == "upgrade_pending"
    assert g(None, "0.8.0")[0] == "upgrade_pending"                                      # never stamped = must be upgraded
    assert g("0.9.0", "0.8.0")[0] == "downgrade" and g("1.0.0", "0.9.5")[0] == "downgrade"
    assert versions.satisfies(">=0.8,<0.9", "0.8.3") and not versions.satisfies(">=0.9", "0.8.3") and versions.satisfies("", "1.0") and not versions.satisfies("garbage", "1.0")
    assert versions.compare("0.10.0", "0.9.0") == 1 and versions.compare("1.0", "1.0.0") == 0       # numeric, not alphabetic, ordering


def test_fresh_companies_are_stamped_current(env):
    with env.plane.company_scope(env.A) as site:
        assert get_setting("framework_version") == velora.__version__
        assert state.check_site(site) == ("ok", velora.__version__)
        assert patches.applied() == set()                                                 # no patches exist yet
    assert env.plane.pending_upgrade()[0] == "ok"


def test_new_code_is_refused_by_a_database_that_has_not_been_upgraded(env):
    make_old(env, [env.B], cp=False)                                                      # only company B is behind
    app = create_app(auto_init=False, workspace=env.ws, plane=env.plane)
    c = TestClient(app)
    env.plane.identity.create_user("u@example.com", "U", PW)
    for cid in (env.A, env.B):
        env.plane.identity.grant("u@example.com", cid, ["System Manager"])
    assert c.post("/api/auth/login", json={"email": "u@example.com", "password": PW}).status_code == 200
    ok = c.get("/api/doctypes", headers={**H, "X-Velora-Company": env.A})
    blocked = c.get("/api/doctypes", headers={**H, "X-Velora-Company": env.B})
    assert ok.status_code == 200
    assert blocked.status_code == 503 and blocked.json()["error"] == "UpgradePending" and "velora upgrade" in blocked.json()["message"]
    with env.plane.company_scope(env.B) as site:
        set_setting("framework_version", "9.9.0")
        site.gate_cache = None
    again = c.get("/api/doctypes", headers={**H, "X-Velora-Company": env.B})
    assert again.status_code == 503 and "newer than the installed code" in again.json()["message"]       # a downgrade is refused too


def test_control_plane_gate_blocks_everything_until_upgraded(env):
    make_old(env, [])                                                                     # control plane only
    c = TestClient(create_app(auto_init=False, workspace=env.ws, plane=env.plane))
    r = c.get("/api/doctypes")
    assert r.status_code == 503 and r.json()["error"] == "UpgradePending"
    assert c.get("/api/health").status_code == 503                                        # a load balancer drains it
    assert c.get("/api/auth/config").status_code == 200                                   # the Desk can still load its sign-in screen
    env.plane.migrate()
    env.plane._gate = None
    c2 = TestClient(create_app(auto_init=False, workspace=env.ws, plane=env.plane))
    assert c2.get("/api/health").json() == {"status": "ok", "version": velora.__version__}


# ============================== maintenance mode ==============================
def test_maintenance_mode(env):
    ws = env.ws
    maintenance.enable(ws, "Back in a minute")
    c = TestClient(create_app(auto_init=False, workspace=ws, plane=env.plane))
    r = c.get("/api/doctypes")
    assert r.status_code == 503 and r.json() == {"error": "Maintenance", "message": "Back in a minute", "details": None} and r.headers["retry-after"] == "15"
    h = c.get("/api/health")
    assert h.status_code == 503 and h.json()["status"] == "maintenance" and h.json()["version"] == velora.__version__
    assert c.post("/api/auth/login", json={"email": "root@example.com", "password": PW}).status_code == 503
    assert c.get("/api/auth/config").status_code == 200 and c.get("/api/theme/public").status_code == 200       # the Desk can still render its screen
    assert maintenance.status(ws)["message"] == "Back in a minute"
    maintenance.disable(ws)
    c2 = TestClient(create_app(auto_init=False, workspace=ws, plane=env.plane))
    assert c2.get("/api/health").json()["status"] == "ok" and c2.get("/api/auth/config").status_code == 200
    assert maintenance.status(ws) is None
    maintenance.disable(ws)                                                              # idempotent


# ============================== data patches ==============================
def write_patches(ws, text, app="shop"):
    (ws.app_path(app) / app / "patches.txt").write_text(text)


def test_patch_file_parsing(env):
    write_patches(env.ws, "# c\n[pre_model_sync]\nshop.patches.a  # trailing comment\n\n[post_model_sync]\nshop.patches.b\nshop.patches.c\n")
    d = patches.discover("shop")
    assert d == {"pre_model_sync": ["shop.patches.a"], "post_model_sync": ["shop.patches.b", "shop.patches.c"]}
    write_patches(env.ws, "shop.patches.x\n")
    assert patches.discover("shop")["post_model_sync"] == ["shop.patches.x"]              # no header = after the schema sync
    for bad, frag in (("[sometimes]\nx.y\n", "unknown section"), ("not a path\n", "not a dotted module path"), ("shop.p.a\nshop.p.a\n", "listed twice")):
        write_patches(env.ws, bad)
        with pytest.raises(PatchError, match=frag):
            patches.discover("shop")
    assert patches.discover("no_such_package") == {"pre_model_sync": [], "post_model_sync": []}


def test_patches_run_once_in_order_and_are_logged(env):
    (env.ws.app_path("shop") / "shop" / "patches").mkdir()
    for n in ("p1", "p2", "p3"):
        (env.ws.app_path("shop") / "shop" / "patches" / f"{n}.py").write_text(f'ORDER = []\nimport builtins\ndef execute():\n    getattr(builtins, "_order", None) is None and setattr(builtins, "_order", [])\n    builtins._order.append("{n}")\n')
    (env.ws.app_path("shop") / "shop" / "patches" / "__init__.py").write_text("")
    write_patches(env.ws, "[pre_model_sync]\nshop.patches.p1\n[post_model_sync]\nshop.patches.p2\nshop.patches.p3\n")
    import builtins
    builtins._order = []
    try:
        with env.plane.company_scope(env.A):
            assert patches.pending(["shop"], "pre_model_sync") == ["shop.patches.p1"]
            assert patches.run(["shop"], "pre_model_sync") == ["shop.patches.p1"]
            assert patches.run(["shop"], "post_model_sync") == ["shop.patches.p2", "shop.patches.p3"]
            assert builtins._order == ["p1", "p2", "p3"]
            assert patches.run(["shop"], "pre_model_sync") == [] and patches.run(["shop"], "post_model_sync") == []        # exactly once
            assert patches.applied() == {"shop.patches.p1", "shop.patches.p2", "shop.patches.p3"}
    finally:
        del builtins._order


def test_a_failing_patch_changes_nothing_and_can_be_retried(env):
    change_app(env.ws, patch=("bad", "import velora\ndef execute():\n    d = velora.get_doc('Product', velora.get_list('Product', fields=['name'])[0]['name'])\n    d.title = 'half done'\n    d.save(ignore_permissions=True)\n    raise ValueError('nope')\n"))
    with env.plane.company_scope(env.A):
        with pytest.raises(PatchError, match=r"Patch shop\.patches\.bad failed: ValueError: nope") as e:
            patches.run(["shop"], "post_model_sync")
        assert e.value.details == {"patch": "shop.patches.bad"}
        assert patches.applied() == set()
        assert [d["title"] for d in velora.get_list("Product", fields=["title"])] == ["Widget"]          # the half-done write rolled back with it
    (env.ws.app_path("shop") / "shop" / "patches" / "bad.py").write_text("def execute():\n    pass\n")
    import importlib
    sys.modules.pop("shop.patches.bad", None)
    importlib.invalidate_caches()
    with env.plane.company_scope(env.A):
        assert patches.run(["shop"], "post_model_sync") == ["shop.patches.bad"]                          # simply retried next time


def test_patch_without_execute_or_with_import_error(env):
    change_app(env.ws, patch=("noexec", "X = 1\n"))
    with env.plane.company_scope(env.A):
        with pytest.raises(PatchError, match="must define execute"):
            patches.run(["shop"], "post_model_sync")
    write_patches(env.ws, "shop.patches.missing_module\n")
    with env.plane.company_scope(env.A):
        with pytest.raises(PatchError, match="missing_module"):
            patches.run(["shop"], "post_model_sync")


def test_fresh_installs_record_existing_patches_without_running_them(env, tmp_path):
    marker = tmp_path / "ran.txt"
    change_app(env.ws, patch=("old", f"def execute():\n    open({str(marker)!r}, 'w').write('ran')\n"))
    co = env.plane.provisioning.provision_company("Group", "Fresh Co", apps=["shop"])             # created AFTER the patch exists
    with env.plane.company_scope(co["id"]):
        assert "shop.patches.old" in patches.applied()                                           # counted as done ...
        assert patches.pending(["shop"], "post_model_sync") == []
    assert not marker.exists()                                                                    # ... never executed: there is no old data to fix


# ============================== schema sync: safe widening + warnings ==============================
def migrate_company(env, cid):
    with env.plane.company_scope(cid) as site:
        site.load()
        return schema.migrate()


def test_lossy_type_change_is_reported_never_applied(env):
    change_app(env.ws, version="0.0.2", field_type="Int")                                         # title Data -> Int
    plan = migrate_company(env, env.A)
    assert len(plan) == 1 and plan[0].startswith("WARNING: tab_product.title") and "ship a data patch" in plan[0]
    assert migrate_company(env, env.A) == plan                                                    # reported again until a patch fixes it
    with env.plane.company_scope(env.A) as site:
        types = {c["name"]: str(c["type"]).upper() for c in inspect(site.engine).get_columns("tab_product")}
    assert "INT" not in types["title"]                                                            # the column is untouched


@pytest.mark.skipif(not PG_ROOT_PW, reason="needs PostgreSQL for ALTER COLUMN")
def test_pg_widening_is_applied_and_shrinking_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("G")
    co = plane.provisioning.provision_company("G", "PgCo", apps=["shop"], db="postgres", root_password=PG_ROOT_PW)
    try:
        def title_length():
            with plane.company_scope(co["id"]) as site:
                return next(c["type"].length for c in inspect(site.engine).get_columns("tab_product") if c["name"] == "title")

        def migrate(dry=False):
            with plane.company_scope(co["id"]) as site:
                site.load()
                return schema.migrate(dry_run=dry)
        assert title_length() == 255
        change_app(ws, version="0.0.2", length=500)
        assert migrate(dry=True) == ["ALTER TABLE tab_product ALTER COLUMN title TYPE VARCHAR(500)"] and title_length() == 255     # a dry run changes nothing
        assert migrate() == ["ALTER TABLE tab_product ALTER COLUMN title TYPE VARCHAR(500)"] and title_length() == 500              # widening is applied
        assert migrate() == []                                                                                                          # and is then idempotent
        change_app(ws, version="0.0.3", length=100)
        assert migrate() == [] and title_length() == 500                                                                             # shrinking is never automatic
    finally:
        plane.provisioning.drop_company(co["id"], root_password=PG_ROOT_PW)
        plane.dispose()
        from velora import dbadmin
        if plane.cfg.get("provisioned_db"):
            dbadmin.drop_pg("localhost", 5432, "postgres", PG_ROOT_PW, plane.cfg["db_name"], plane.cfg["db_user"])


# ============================== backup / restore ==============================
def test_sqlite_backup_and_restore_round_trip(env):
    co = env.plane.registry.get_company(env.A)
    f = env.plane.sqlite_path(co)
    arc = provision.backup_database({"db_type": "sqlite"}, f, env.ws.root / "backups" / "t", "A")
    assert arc.name.endswith(".db.gz") and oct(arc.stat().st_mode & 0o777) == "0o600"
    with env.plane.company_scope(env.A):
        velora.new_doc("Product", title="after backup").insert()
    t = next(t for t in collect_targets(env.ws) if t.id == env.A)
    from velora.upgrade.engine import restore_target
    restore_target(t, arc)
    assert titles(env, env.A) == ["Widget"]                                                       # data rolled back
    assert f.with_name(f.name + ".pre-restore").exists()                                          # the state we replaced is kept


def test_restore_refuses_bad_backups_and_changes_nothing(env, tmp_path):
    f = env.plane.sqlite_path(env.plane.registry.get_company(env.A))
    before = f.read_bytes()
    import gzip
    empty = tmp_path / "empty.db.gz"; empty.write_bytes(gzip.compress(b""))
    notdb = tmp_path / "notdb.db.gz"; notdb.write_bytes(gzip.compress(b"this is not a sqlite database at all" * 50))
    broken = tmp_path / "broken.db.gz"; broken.write_bytes(b"not gzip")
    for bad, frag in ((empty, "empty"), (notdb, "not a valid database|file is not a database|unreadable|integrity"), (broken, "unreadable")):
        with pytest.raises(Exception, match=frag):
            bk.restore_database({"db_type": "sqlite"}, f, bad)
        assert f.read_bytes() == before
    assert not list(f.parent.glob("*.restoring"))                                                  # no temp files left behind


@pytest.mark.skipif(not PG_ROOT_PW, reason="needs PostgreSQL")
def test_pg_restore_is_atomic(tmp_path, monkeypatch):
    import gzip
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("G")
    co = plane.provisioning.provision_company("G", "PgCo", apps=["shop"], db="postgres", root_password=PG_ROOT_PW)
    try:
        with plane.company_scope(co["id"]):
            velora.new_doc("Product", title="one").insert()
        cfg = plane.router.db_config(plane.registry.get_company(co["id"]))
        arc = provision.backup_database(cfg, None, ws.root / "backups" / "t", "pg")
        with plane.company_scope(co["id"]):
            velora.new_doc("Product", title="two").insert()
        plane.router.forget(co["id"])
        bk.restore_database(cfg, None, arc)
        with plane.company_scope(co["id"]):
            assert [d["title"] for d in velora.get_list("Product", fields=["title"])] == ["one"]
            velora.new_doc("Product", title="three").insert()
        plane.router.forget(co["id"])
        bad = tmp_path / "bad.sql.gz"
        good = gzip.decompress(arc.read_bytes())
        bad.write_bytes(gzip.compress(good + b"\nTHIS IS NOT SQL;\n"))                          # fails at the very end, after the schema was rebuilt
        with pytest.raises(WorkspaceError, match="rolled back"):
            bk.restore_database(cfg, None, bad)
        with plane.company_scope(co["id"]):
            assert sorted(d["title"] for d in velora.get_list("Product", fields=["title"])) == ["one", "three"]   # untouched: all-or-nothing
    finally:
        plane.provisioning.drop_company(co["id"], root_password=PG_ROOT_PW)
        plane.dispose()


# ============================== the upgrade engine ==============================
DISCOUNT = {"fieldname": "discount", "fieldtype": "Float"}


def psql_version(env, cid):
    with env.plane.company_scope(cid):
        return get_setting("framework_version")


def app_versions(env, cid):
    from velora.db.system import installed_app
    with env.plane.company_scope(cid):
        with db.transaction() as conn:
            return dict(conn.execute(select(installed_app.c.name, installed_app.c.version)).all())


def test_nothing_to_do_changes_nothing(env):
    rep = env.engine().run()
    assert rep["status"] == "up_to_date" and rep["snapshot"] is None
    assert [t["id"] for t in rep["targets"]] == ["control-plane", env.A, env.B] and all(t["status"] == "up_to_date" for t in rep["targets"])
    assert maintenance.status(env.ws) is None and not (env.ws.root / ".upgrade.lock").exists() and not list((env.ws.root / "backups").glob("upgrade-*"))


def test_dry_run_reports_the_plan_and_touches_nothing(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    rep = env.engine().run(dry_run=True)
    assert rep["status"] == "dry_run" and all(t["needs_upgrade"] for t in rep["targets"])
    co = next(t for t in rep["targets"] if t["id"] == env.A)
    assert co["from"] == OLD and co["schema_changes"] == 1 and co["patches"] == ["shop.patches.tidy"]
    assert "discount" not in columns(env, env.A) and psql_version(env, env.A) == OLD and titles(env, env.A) == ["Widget"]
    assert not list((env.ws.root / "backups").glob("upgrade-*")) and maintenance.status(env.ws) is None


def test_upgrade_applies_schema_patches_and_versions_to_every_database(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    rep = env.engine().run()
    assert rep["status"] == "success" and [t["status"] for t in rep["targets"]] == ["upgraded"] * 3
    for cid in (env.A, env.B):
        assert "discount" in columns(env, cid)
        assert titles(env, cid) == ["Widget [patched]"]                                    # the data patch ran in each company
        assert psql_version(env, cid) == velora.__version__ and app_versions(env, cid) == {"shop": "0.0.2"}
        assert env.plane.registry.get_company(cid)["schema_version"] == velora.__version__
    assert env.plane.schema_version() == velora.__version__
    snap = Path(rep["snapshot"])
    manifest = json.loads((snap / "manifest.json").read_text())
    assert set(manifest["targets"]) == {"control-plane", env.A, env.B} and all((snap / f).exists() for f in manifest["targets"].values())
    assert maintenance.status(env.ws) is None and not (env.ws.root / ".upgrade.lock").exists()
    again = env.engine().run()
    assert again["status"] == "up_to_date" and titles(env, env.A) == ["Widget [patched]"]   # patches never re-run


def test_upgrade_makes_pending_databases_servable_again(env):
    make_old(env)
    env.plane.identity.create_user("u@example.com", "U", PW)
    env.plane.identity.grant("u@example.com", env.A, ["System Manager"])
    get = lambda: TestClient(create_app(auto_init=False, workspace=env.ws, plane=env.plane))
    c = get()
    assert c.get("/api/health").status_code == 503
    env.engine().run()
    env.plane._gate = None                                                                              # (a running server's cached verdict expires after 5s)
    c = get()
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/auth/login", json={"email": "u@example.com", "password": PW}).status_code == 200
    assert c.get("/api/doctypes", headers={**H, "X-Velora-Company": env.A}).status_code == 200


def test_a_failure_anywhere_restores_EVERY_database(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    with env.plane.company_scope(env.A):
        velora.new_doc("Product", title="second").insert()
    rep = env.engine().run()
    assert rep["status"] == "rolled_back"
    by = {t["id"]: t for t in rep["targets"]}
    assert by[env.B]["status"] == "failed (restored)" and "boom in COMP-002" in by[env.B]["error"] and by[env.A]["status"] == "rolled_back"
    assert all(r["restored"] for r in rep["rollback"]) and [r["id"] for r in rep["rollback"]] == [env.B, env.A, "control-plane"]    # reverse order
    for cid in (env.A, env.B):
        assert "discount" not in columns(env, cid) and psql_version(env, cid) == OLD and app_versions(env, cid) == {"shop": "0.0.1"}
        with env.plane.company_scope(cid):
            assert patches.applied() == set()
    assert titles(env, env.A) == ["Widget", "second"] and titles(env, env.B) == ["Widget"]            # data exactly as before the attempt
    assert env.plane.schema_version() == OLD
    assert maintenance.status(env.ws) is None and not (env.ws.root / ".upgrade.lock").exists()
    with env.plane.company_scope(env.A):
        velora.new_doc("Product", title="still works").insert()                                       # and the database is usable


def test_partial_mode_upgrades_what_it_can_and_leaves_the_failure_pending(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    rep = env.engine(partial=True).run()
    assert rep["status"] == "partial"
    by = {t["id"]: t["status"] for t in rep["targets"]}
    assert by == {"control-plane": "upgraded", env.A: "upgraded", env.B: "failed"}
    assert titles(env, env.A) == ["Widget [patched]"] and titles(env, env.B) == ["Widget"]            # B's failed patch left no half-done data
    t = next(t for t in collect_targets(env.ws) if t.id == env.B)
    assert inspect_target(t)["gate"] == "upgrade_pending"                                              # B keeps answering 503 until fixed


def test_failure_without_a_backup_is_reported_honestly(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    rep = env.engine(backup=False).run()
    assert rep["status"] == "failed" and "could NOT be restored" in rep["rollback"] and rep["snapshot"] is None
    assert "discount" in columns(env, env.A)                                                            # A really was left upgraded: the report says so


def test_a_failed_health_check_rolls_everything_back(env, monkeypatch):
    from velora.upgrade import engine as eng
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT)
    real = eng.health_check
    monkeypatch.setattr(eng, "health_check", lambda t: (_ for _ in ()).throw(UpgradeError("looks unhealthy")) if t.id == env.A else real(t))
    rep = env.engine().run()
    assert rep["status"] == "rolled_back" and "looks unhealthy" in next(t for t in rep["targets"] if t["id"] == env.A)["error"]
    assert "discount" not in columns(env, env.A) and psql_version(env, env.A) == OLD


def test_only_selects_targets_and_rejects_unknown_ones(env):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT)
    rep = env.engine(only=[env.A]).run()
    assert [t["id"] for t in rep["targets"]] == [env.A] and "discount" in columns(env, env.A) and "discount" not in columns(env, env.B)
    with pytest.raises(UpgradeError, match="Unknown target"):
        env.engine(only=["COMP-999"]).run()


def test_old_snapshots_are_pruned(env):
    for v in ("0.0.2", "0.0.3", "0.0.4"):
        make_old(env)
        change_app(env.ws, version=v)
        assert UpgradeEngine(env.ws, log=lambda m: None, keep_snapshots=2).run()["status"] in ("success", "up_to_date")
        time.sleep(1.1)                                                                                  # snapshot names are per-second
    assert len(list((env.ws.root / "backups").glob("upgrade-*"))) <= 2


def test_control_plane_schema_is_upgraded_additively(env):
    with env.plane.engine.begin() as c:
        c.execute(text("ALTER TABLE cp_user DROP COLUMN full_name"))
    assert env.plane.migrate(dry_run=True) == ["ALTER TABLE cp_user ADD COLUMN full_name VARCHAR(200)"]
    assert "full_name" not in {c["name"] for c in inspect(env.plane.engine).get_columns("cp_user")}      # dry run changed nothing
    env.plane.migrate()
    assert "full_name" in {c["name"] for c in inspect(env.plane.engine).get_columns("cp_user")} and env.plane.migrate() == []


# ---------------- safety: locks and compatibility ----------------
def test_only_one_upgrade_at_a_time(env):
    lock = env.ws.root / ".upgrade.lock"
    with upgrade_lock(env.ws) as owned:
        assert owned and lock.exists()
        with pytest.raises(UpgradeError, match="already running"):
            with upgrade_lock(env.ws):
                pass
        with pytest.raises(UpgradeError, match="already running"):
            env.engine().run()
    assert not lock.exists()
    lock.write_text(json.dumps({"pid": 2 ** 22 + 12345}))                                                # a crashed run left a stale lock
    with upgrade_lock(env.ws) as owned:
        assert owned
    lock.write_text(json.dumps({"pid": os.getppid()}))                                                   # held by our parent (`velora update`)
    with upgrade_lock(env.ws) as owned:
        assert owned is False
    assert lock.exists()
    lock.unlink()
    lock.write_text("garbage")
    with upgrade_lock(env.ws):
        pass
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    env.engine().run()
    assert not lock.exists()                                                                             # released even after a failed upgrade


def test_apps_declaring_an_incompatible_framework_are_refused(env):
    hooks = env.ws.app_path("shop") / "shop" / "hooks.py"
    hooks.write_text(hooks.read_text().replace('required_velora = ""', 'required_velora = ">=9.0"'))
    fresh_process("shop", env.ws.app_path("shop"))
    t = next(t for t in collect_targets(env.ws) if t.id == env.A)
    import re
    major, minor = (int(x) for x in velora.__version__.split(".")[:2])                                   # never a hard-coded framework version: it changes every release
    with pytest.raises(UpgradeError, match=rf"shop requires velora >=9\.0, but velora {re.escape(velora.__version__)} is installed"):
        inspect_target(t)
    hooks.write_text(hooks.read_text().replace(">=9.0", f">={major}.{minor},<{major}.{minor + 1}"))
    fresh_process("shop", env.ws.app_path("shop"))
    assert inspect_target(t)["gate"] == "ok"


def test_app_downgrades_are_refused(env):
    from velora.db.system import installed_app
    with env.plane.company_scope(env.A):
        with db.transaction() as conn:
            conn.execute(installed_app.update().where(installed_app.c.name == "shop").values(version="2.0.0"))
    t = next(t for t in collect_targets(env.ws) if t.id == env.A)
    with pytest.raises(UpgradeError, match="shop: this database is at version 2.0.0 but the code is 0.0.1"):
        inspect_target(t)


# ============================== velora update (code from git / pip) ==============================
import shutil
import subprocess

from velora.upgrade import doctor, update as upd

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
needs_git = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True, text=True).stdout.strip()


def track_app(env, tmp_path, app="shop"):
    """Make apps/<app> a git checkout that follows a bare 'remote' (what `velora get-app` leaves behind)."""
    d = env.ws.app_path(app)
    (d / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git(d, "init", "-q", "-b", "main"); git(d, "add", "-A"); git(d, "commit", "-q", "-m", "v1")
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(d, "remote", "add", "origin", str(bare)); git(d, "push", "-q", "-u", "origin", "main")
    return bare


def release(tmp_path, bare, **change):
    """Publish a new app release to the remote (as its developer would)."""
    dev = tmp_path / "dev"
    shutil.rmtree(dev, ignore_errors=True)
    git(tmp_path, "clone", "-q", str(bare), str(dev))
    W = type("W", (), {"app_path": lambda self, a: dev})()
    change_app(W, **change)
    git(dev, "add", "-A"); git(dev, "commit", "-q", "-m", "release"); git(dev, "push", "-q")


def run_update(env, **kw):
    fresh_process("shop", env.ws.app_path("shop"))                                   # every real `velora update` is a new process
    return upd.update(env.ws, log=lambda m: None, **kw)


@needs_git
def test_check_updates_sees_new_commits_versions_and_local_changes(env, tmp_path):
    bare = track_app(env, tmp_path)
    s = upd.app_status(env.ws, "shop")
    assert s["repo"] and s["behind"] == 0 and not s["dirty"] and s["branch"] == "main"
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT)
    s = upd.app_status(env.ws, "shop")
    assert s["behind"] == 1 and s["latest"] == "0.0.2" and s["version"] == "0.0.1"
    (env.ws.app_path("shop") / "README.md").write_text("local edit")
    assert upd.app_status(env.ws, "shop")["dirty"] is True
    other = make_app(env.ws, "plain", "Thing", "Plain")                                    # not a git checkout at all
    assert upd.app_status(env.ws, "plain")["note"] == "not a git checkout"
    git(other, "init", "-q", "-b", "main")
    assert upd.app_status(env.ws, "plain")["note"] == "no upstream branch"
    res = upd.check_updates(env.ws)
    assert res["framework"] == {"current": velora.__version__, "latest": None, "source": "(none configured)"} and {a["name"] for a in res["apps"]} == {"shop", "plain"}


@needs_git
def test_update_pulls_the_release_and_upgrades_every_database(env, tmp_path):
    bare = track_app(env, tmp_path)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    marker = tmp_path / "restarted"
    rep = run_update(env, restart_command=f"touch {marker}")
    assert rep["status"] == "success" and rep["code"]["apps"] == [{"name": "shop", "from": "0.0.1", "to": "0.0.2", "commits": 1}]
    assert rep["upgrade"]["status"] == "success" and rep["restart"]["ok"] is True and marker.exists()
    for cid in (env.A, env.B):
        assert "discount" in columns(env, cid) and titles(env, cid) == ["Widget [patched]"] and app_versions(env, cid) == {"shop": "0.0.2"}
    assert maintenance.status(env.ws) is None and not (env.ws.root / ".upgrade.lock").exists()
    assert list((env.ws.root / "logs").glob("upgrade-*.json"))                                  # a report is kept
    assert upd.app_status(env.ws, "shop")["behind"] == 0
    # Everything is now at the code's version: further checks change nothing, however often they run.
    assert run_update(env)["status"] == "up_to_date"
    assert run_update(env)["status"] == "up_to_date"


@needs_git
def test_a_failing_release_rolls_back_the_code_AND_the_data(env, tmp_path):
    bare = track_app(env, tmp_path)
    old_sha = git(env.ws.app_path("shop"), "rev-parse", "HEAD")
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    rep = run_update(env)
    assert rep["status"] == "rolled_back" and "data upgrade failed" in rep["error"]
    assert rep["upgrade"]["status"] == "rolled_back"
    assert rep["code_rollback"]["apps"] == [{"name": "shop", "restored": True, "sha": old_sha[:10]}]
    assert git(env.ws.app_path("shop"), "rev-parse", "HEAD") == old_sha                          # the code is back on the old commit ...
    assert '"0.0.1"' in (env.ws.app_path("shop") / "shop" / "__init__.py").read_text()
    for cid in (env.A, env.B):                                                                   # ... and the data is exactly as it was
        assert "discount" not in columns(env, cid) and titles(env, cid) == ["Widget"] and psql_version(env, cid) == velora.__version__
    assert maintenance.status(env.ws) is None and not (env.ws.root / ".upgrade.lock").exists()
    assert upd.app_status(env.ws, "shop")["behind"] == 1                                         # the bad release is still available to retry once fixed


@needs_git
def test_local_changes_block_the_update_and_nothing_is_touched(env, tmp_path):
    bare = track_app(env, tmp_path)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT)
    sha = git(env.ws.app_path("shop"), "rev-parse", "HEAD")
    (env.ws.app_path("shop") / "shop" / "__init__.py").write_text('__version__ = "0.0.1"  # hacked locally\n')
    with pytest.raises(WorkspaceError, match="uncommitted local changes.*shop"):
        run_update(env)
    assert git(env.ws.app_path("shop"), "rev-parse", "HEAD") == sha and maintenance.status(env.ws) is None
    assert "discount" not in columns(env, env.A)
    # local edits do NOT block when the app is already current
    git(env.ws.app_path("shop"), "checkout", "--", ".")
    git(env.ws.app_path("shop"), "pull", "-q")
    (env.ws.app_path("shop") / "README.md").write_text("notes")
    assert run_update(env, do_apps=True)["status"] in ("success", "up_to_date")


@needs_git
def test_update_dry_run_changes_nothing(env, tmp_path):
    bare = track_app(env, tmp_path)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    sha = git(env.ws.app_path("shop"), "rev-parse", "HEAD")
    rep = run_update(env, dry_run=True)
    assert rep["status"] == "dry_run" and rep["code"]["apps"] == [{"name": "shop", "behind": 1, "to": "0.0.2"}]
    assert git(env.ws.app_path("shop"), "rev-parse", "HEAD") == sha and "discount" not in columns(env, env.A) and maintenance.status(env.ws) is None


@needs_git
def test_update_only_selected_apps_and_unknown_app(env, tmp_path):
    bare = track_app(env, tmp_path)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT)
    with pytest.raises(WorkspaceError, match="Not in this workspace: ghost"):
        run_update(env, apps=["ghost"])
    assert run_update(env, do_apps=False)["status"] == "up_to_date"                              # --no-apps: code left alone
    assert upd.app_status(env.ws, "shop")["behind"] == 1


@needs_git
def test_restart_failure_is_reported_but_does_not_undo_a_good_upgrade(env, tmp_path):
    bare = track_app(env, tmp_path)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT)
    rep = run_update(env, restart_command="echo cannot restart >&2; exit 3")
    assert rep["status"] == "success" and rep["restart"]["ok"] is False and "cannot restart" in rep["restart"]["output"]
    assert "discount" in columns(env, env.A)
    ws2 = env.ws.common_config()
    env.ws.common_config_file.write_text(json.dumps({**ws2, "update": {"restart_command": f"touch {tmp_path / 'configured'}"}}))
    release(tmp_path, bare, version="0.0.3", field={"fieldname": "note", "fieldtype": "Data"})
    assert run_update(env)["restart"]["ok"] is True and (tmp_path / "configured").exists()       # the command can come from the workspace config


class _CP:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def fake_pip(monkeypatch, calls, install_rc=0):
    real = upd._run

    def fake(cmd, cwd=None, timeout=900):
        if "pip" in cmd:
            calls.append(cmd)
            if "--dry-run" in cmd:
                return _CP(stdout="Would install velora-9.9.9\n")
            return _CP(returncode=install_rc, stderr="ERROR: no matching distribution" if install_rc else "")
        return real(cmd, cwd, timeout)
    monkeypatch.setattr(upd, "_run", fake)


@needs_git
def test_framework_update_uses_the_configured_source_and_rolls_back_pip_on_failure(env, tmp_path, monkeypatch):
    wheels = tmp_path / "wheels"; wheels.mkdir()
    bare = track_app(env, tmp_path)
    calls: list = []
    fake_pip(monkeypatch, calls)
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    assert upd.framework_latest(str(wheels)) == "9.9.9" and upd.pip_target(str(wheels)) == (["--find-links", str(wheels.resolve())], "velora")
    rep = run_update(env, framework_source=str(wheels))
    assert rep["status"] == "rolled_back"
    install = [c for c in calls if "--dry-run" not in c]
    assert install[0][-1] == "velora" and "--upgrade" in install[0] and "--find-links" in install[0]       # 1. upgrade velora from the source
    assert install[-1][-1] == f"velora=={velora.__version__}" and "--find-links" in install[-1]             # 2. and put the old version back
    assert rep["code_rollback"]["framework"]["restored"] is True and rep["code_rollback"]["apps"][0]["restored"] is True


@needs_git
def test_a_framework_install_failure_aborts_before_any_data_is_touched(env, tmp_path, monkeypatch):
    calls: list = []
    fake_pip(monkeypatch, calls, install_rc=1)
    rep = run_update(env, framework_source=str(tmp_path))
    assert rep["status"] == "rolled_back" and "pip could not install velora" in rep["error"] and "no matching distribution" in rep["error"]
    assert rep["upgrade"] is None and maintenance.status(env.ws) is None and "discount" not in columns(env, env.A)


def test_framework_source_forms(tmp_path):
    whl = tmp_path / "velora-9.0.0-py3-none-any.whl"; whl.write_text("x")
    assert upd.pip_target(None) is None and upd.pip_target("velora>=1.0") == ([], "velora>=1.0")
    assert upd.pip_target(str(whl)) == (["--find-links", str(tmp_path.resolve())], str(whl.resolve()))
    assert upd.framework_latest(str(whl)) == "9.0.0"                                              # read from the wheel name, no pip needed
    old = tmp_path / "velora-0.0.1-py3-none-any.whl"; old.write_text("x")
    assert upd.framework_latest(str(old)) is None                                                 # older than what is installed
    assert upd._app_requirements.__name__ == "_app_requirements"


# ============================== doctor ==============================
def checks(env_or_ws):
    return {c["check"]: c for c in doctor.run_checks(env_or_ws)}


def test_doctor_passes_a_healthy_installation(env):
    c = checks(env.ws)
    assert not [x for x in c.values() if x["status"] == "fail"], c
    assert c["Python"]["status"] == "ok" and c["Master key"]["status"] == "ok" and c["Control plane"]["status"] == "ok" and c[f"{env.A} Company A"]["status"] == "ok"
    assert "up to date" in c[f"{env.A} Company A"]["detail"]
    assert "ok" in doctor.format_report(list(c.values())).splitlines()[0].lower() and "0 failure(s)" in doctor.format_report(list(c.values()))


def test_doctor_explains_every_problem_and_the_fix(env, tmp_path):
    assert checks(None)["Workspace"]["status"] == "fail" and "velora init" in checks(None)["Workspace"]["fix"]
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT)
    maintenance.enable(env.ws)
    (env.ws.root / ".upgrade.lock").write_text("{}")
    mk = env.ws.root / "platform" / "master.key"
    mk.chmod(0o644)
    c = checks(env.ws)
    assert c[f"{env.A} Company A"]["status"] == "warn" and "needs upgrade" in c[f"{env.A} Company A"]["detail"] and "velora upgrade" in c[f"{env.A} Company A"]["fix"]
    assert "schema change" in c[f"{env.A} Company A"]["detail"]
    assert c["Maintenance mode"]["status"] == "warn" and c["Upgrade lock"]["status"] == "warn"
    assert c["Master key"]["status"] == "warn" and "chmod 600" in c["Master key"]["fix"]
    maintenance.disable(env.ws)
    (env.ws.root / ".upgrade.lock").unlink()
    mk.chmod(0o600)
    env.plane.sqlite_path(env.plane.registry.get_company(env.B)).unlink()
    env.plane.router.forget(env.B)
    c = checks(env.ws)
    assert c["Databases"]["status"] == "fail" and env.B in c["Databases"]["detail"] and "MISSING" in c["Databases"]["detail"] and not env.plane.sqlite_path(env.plane.registry.get_company(env.B)).exists()
    mk.rename(mk.with_name("master.key.bak"))
    assert checks(env.ws)["Master key"]["status"] == "fail"


# ============================== quickstart ==============================
def test_quickstart_gives_a_working_signed_in_system_in_one_call(tmp_path, monkeypatch):
    from velora import quickstart as qs
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE"):
        monkeypatch.delenv(k, raising=False)
    res = qs.quickstart(str(tmp_path / "start"), email="boss@acme.ng", password=None, company="Acme Ltd", sample=True, log=lambda m: None)
    assert res["generated_password"] is True and len(res["password"]) == 16 and res["company"] == "COMP-001"
    ws = Workspace(tmp_path / "start")
    plane = ControlPlane.open(ws)
    try:
        c = TestClient(create_app(auto_init=False, workspace=ws, plane=plane))
        r = c.post("/api/auth/login", json={"email": "boss@acme.ng", "password": res["password"]})
        assert r.status_code == 200 and [x["name"] for x in r.json()["data"]["companies"]] == ["Acme Ltd"] and r.json()["data"]["companies"][0]["roles"] == ["System Manager"]
        dts = c.get("/api/doctypes", headers={**H, "X-Velora-Company": "COMP-001"}).json()["data"]
        names = [d["name"] for d in dts]
        assert "Contact" in names                                                                         # the sample app is installed and usable
        assert {"Notification Rule", "Notification Log", "Search Index"} <= set(names)                    # notifications and search come built in
        assert ws.common_config()["default_apps"] == ["velora_notify", "velora_search"] and ws.common_config()["auto_upgrade"] is True
        assert c.get("/api/health").json()["status"] == "ok"
        assert not [x for x in doctor.run_checks(ws) if x["status"] == "fail"]
        with pytest.raises(WorkspaceError, match="already set up"):
            qs.quickstart(str(tmp_path / "start"), email="x@y.com", password=None, company="Again", log=lambda m: None)
    finally:
        plane.dispose()


def test_quickstart_options_and_validation(tmp_path, monkeypatch):
    from velora import quickstart as qs
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    with pytest.raises(WorkspaceError, match="administrator email"):
        qs.quickstart(str(tmp_path / "a"), email="nope", password=None, company="X", log=lambda m: None)
    res = qs.quickstart(str(tmp_path / "b"), email="a@b.com", password="my own long passphrase", company="X", sample=False, log=lambda m: None)
    assert res["password"] is None and res["generated_password"] is False and not Workspace(tmp_path / "b").apps()
    with pytest.raises(ValidationError := __import__("velora").exceptions.ValidationError, match="at least 10"):
        qs.quickstart(str(tmp_path / "c"), email="a@b.com", password="short", company="X", log=lambda m: None)
    assert not (tmp_path / "c" / "platform" / "control_plane.json").exists()                              # a failed quickstart leaves nothing half-built
    pw = {qs.generate_password() for _ in range(50)}
    assert len(pw) == 50 and all(len(p) == 16 and p.isalnum() for p in pw)


# ============================== CLI wiring ==============================
def cli(capsys, *argv):
    code = main(list(argv))
    o = capsys.readouterr()
    return code, o.out, o.err


def test_cli_quickstart_prints_the_password_once(tmp_path, monkeypatch, capsys):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE"):
        monkeypatch.delenv(k, raising=False)
    code, out, _ = cli(capsys, "quickstart", str(tmp_path / "qs"), "--email", "a@b.com", "--company", "Acme", "--no-start")
    assert code == 0 and "All set." in out and "shown ONCE" in out and "master.key" in out and "velora start" in out
    code, out, err = cli(capsys, "quickstart", str(tmp_path / "qs2"), "--email", "a@b.com", "--company", "Acme", "--password", "a long passphrase 1", "--no-start", "--no-sample")
    assert code == 0 and "shown ONCE" not in out
    assert cli(capsys, "quickstart", str(tmp_path / "qs"), "--email", "a@b.com", "--no-start")[2].startswith("Error: ") 


def test_cli_upgrade_update_maintenance_and_restore(env, capsys, tmp_path):
    code, out, _ = cli(capsys, "upgrade")
    assert code == 0 and "already up to date" in out
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    code, out, _ = cli(capsys, "upgrade", "--dry-run")
    assert code == 0 and "Dry run" in out and "pending" in out and "patches: 1 pending" in out and "discount" not in columns(env, env.A)
    assert cli(capsys, "maintenance", "on", "--message", "brb")[0] == 0 and maintenance.status(env.ws)["message"] == "brb"
    assert "ON since" in cli(capsys, "maintenance", "status")[1]
    cli(capsys, "maintenance", "off")
    assert cli(capsys, "maintenance", "status")[1].strip() == "OFF"
    code, out, _ = cli(capsys, "backup", "--all")
    backups = {l.split(":")[0]: l.split(": ", 1)[1] for l in out.strip().splitlines()}
    assert env.A in " ".join(backups) and len(backups) == 3
    code, out, _ = cli(capsys, "upgrade")
    assert code == 0 and "Upgrade complete." in out and "discount" in columns(env, env.A)
    with env.plane.company_scope(env.A):
        velora.new_doc("Product", title="made after the upgrade").insert()
    bk_file = next(v for k, v in backups.items() if env.A in k)
    assert "--yes" in cli(capsys, "restore", bk_file, "--company", env.A)[2]
    code, out, _ = cli(capsys, "restore", bk_file, "--company", env.A, "--yes")
    assert code == 0 and "Safety backup" in out and "restored" in out
    assert "discount" not in columns(env, env.A) and titles(env, env.A) == ["Widget"]                    # back to the state at that backup
    assert cli(capsys, "restore", str(tmp_path / "nope.gz"), "--company", env.A, "--yes")[0] == 1
    assert maintenance.status(env.ws) is None


def test_cli_failed_upgrade_exits_3_and_says_everything_was_restored(env, capsys):
    make_old(env)
    change_app(env.ws, version="0.0.2", field=DISCOUNT, patch=("tidy", FAIL_ON_B_PATCH))
    code, out, _ = cli(capsys, "upgrade")
    assert code == 3 and "UPGRADE FAILED - every database was restored" in out and "boom in COMP-002" in out and "failed (restored)".upper().split()[0] in out.upper()
    code, out, _ = cli(capsys, "upgrade", "--no-backup", "--partial")
    assert code == 3 and "PARTIALLY" in out


def test_cli_doctor_and_version(env, capsys):
    code, out, _ = cli(capsys, "doctor")
    assert code == 0 and "0 failure(s)" in out
    make_old(env)
    assert "needs upgrade" in cli(capsys, "doctor")[1]
    Path(env.ws.root / "platform" / "master.key").rename(env.ws.root / "platform" / "mk.bak")
    assert cli(capsys, "doctor")[0] == 1
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    assert subprocess.run([sys.executable, "-m", "velora.cli", "--version"], capture_output=True, text=True, env=env).stdout.strip() == f"velora {velora.__version__}"


@needs_git
def test_cli_update_check_exit_codes(env, tmp_path, capsys):
    bare = track_app(env, tmp_path)
    code, out, _ = cli(capsys, "update", "--check")
    assert code == 0 and "no update source configured" in out and "up to date" in out
    release(tmp_path, bare, version="0.0.2", field=DISCOUNT)
    code, out, _ = cli(capsys, "update", "--check")
    assert code == 10 and "1 new commit(s) (version 0.0.2)" in out                                          # scripts can alert on exit code 10
    code, out, _ = cli(capsys, "update", "--dry-run")
    assert code == 0 and "Would update shop (1 commit(s) -> 0.0.2)" in out
    code, out, _ = cli(capsys, "update")
    assert code == 0 and out.count("Upgrade complete.") == 1 and "Restart: no restart command configured" in out and "discount" in columns(env, env.A)      # summary shown once


def test_cli_migrate_in_a_workspace_runs_patches_and_stamps(tmp_path, monkeypatch, capsys):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE"):
        monkeypatch.delenv(k, raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    assert cli(capsys, "new-site", "s.local")[0] == 0 and cli(capsys, "--site", "s.local", "install-app", "shop")[0] == 0
    site = site_mod.load_site(ws.site_path("s.local"))
    with site_mod.use(site):
        velora.new_doc("Product", title="Widget").insert()
        set_setting("framework_version", OLD)
    change_app(ws, version="0.0.2", field=DISCOUNT, patch=("tidy", OK_PATCH))
    code, out, _ = cli(capsys, "--site", "s.local", "migrate")
    assert code == 0 and "ADD COLUMN" in out and "patch shop.patches.tidy: done" in out
    site_mod.unload_all()
    site = site_mod.load_site(ws.site_path("s.local"))
    with site_mod.use(site):
        assert get_setting("framework_version") == velora.__version__ and [d["title"] for d in velora.get_list("Product", fields=["title"])] == ["Widget [patched]"]
    assert "Nothing to migrate" in cli(capsys, "--site", "s.local", "migrate")[1]


def test_restore_never_destroys_the_backup_it_is_restoring_from(env, capsys):
    """Regression: the safety copy taken at the start of a restore used to get the same name as the backup being restored."""
    cli(capsys, "backup", "--all")
    code, out, _ = cli(capsys, "backup", "--all")                                      # two backups in the same second: both kept
    assert code == 0 and len(list((env.ws.root / "backups" / "manual").glob(f"*-{env.A}-database*.gz"))) == 2
    first = sorted((env.ws.root / "backups" / "manual").glob(f"*-{env.A}-database*.gz"))[0]
    with env.plane.company_scope(env.A):
        velora.new_doc("Product", title="after the backup").insert()
    before = first.read_bytes()
    code, out, _ = cli(capsys, "restore", str(first), "--company", env.A, "--yes")
    assert code == 0 and first.read_bytes() == before                                    # the source backup is untouched
    assert titles(env, env.A) == ["Widget"]                                              # genuinely restored to the older state
    safety = list((env.ws.root / "backups" / "safety").glob(f"*pre-restore-{env.A}*.gz"))
    assert len(safety) == 1 and safety[0] != first                                       # the pre-restore copy lives elsewhere, under its own name


def test_a_missing_database_file_is_never_silently_recreated(env, capsys):
    f = env.plane.sqlite_path(env.plane.registry.get_company(env.B))
    f.unlink()
    env.plane.router.forget(env.B)
    with pytest.raises(UpgradeError, match=r"COMP-002 Company B: its database file is MISSING"):
        collect_targets(env.ws)
    code, _, err = cli(capsys, "upgrade")
    assert code == 1 and "MISSING" in err and "velora restore" in err
    assert not f.exists()                                                                # no empty database was created behind our back


def test_stale_bytecode_cannot_hide_a_same_second_same_size_update(tmp_path):
    """Regression: `git pull` can rewrite __init__.py within the same second with the same length; Python would reuse the old .pyc."""
    import importlib
    pkg = tmp_path / "stalepkg"
    pkg.mkdir()
    src = pkg / "__init__.py"
    src.write_text('__version__ = "0.0.1"\n')
    sys.path.insert(0, str(tmp_path))
    try:
        stamp = src.stat().st_mtime
        import stalepkg                                                         # writes __pycache__/__init__.cpython-*.pyc
        assert stalepkg.__version__ == "0.0.1"
        src.write_text('__version__ = "0.0.2"\n')                               # same size ...
        os.utime(src, (stamp, stamp))                                           # ... and the same mtime second
        for m in [m for m in sys.modules if m.startswith("stalepkg")]:
            del sys.modules[m]
        importlib.invalidate_caches()
        import stalepkg as again
        assert again.__version__ == "0.0.1"                                     # THE HAZARD: the stale .pyc wins
        for m in [m for m in sys.modules if m.startswith("stalepkg")]:
            del sys.modules[m]
        assert upd._clear_bytecode(tmp_path) >= 1 and not list(pkg.rglob("*.pyc"))
        importlib.invalidate_caches()
        import stalepkg as fixed
        assert fixed.__version__ == "0.0.2"                                     # after clearing, the new code is what runs
    finally:
        sys.path.remove(str(tmp_path))
        for m in [m for m in sys.modules if m.startswith("stalepkg")]:
            del sys.modules[m]


@pytest.mark.skipif(not PG_ROOT_PW, reason="needs PostgreSQL")
def test_quickstart_on_postgresql_is_what_the_server_installer_runs(tmp_path, monkeypatch):
    from velora import dbadmin, quickstart as qs
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    res = qs.quickstart(str(tmp_path / "pg"), email="boss@acme.ng", password=None, company="Acme Ltd", sample=False, db="postgres",
                        db_kwargs={"root_password": PG_ROOT_PW}, log=lambda m: None)
    ws = Workspace(tmp_path / "pg")
    plane = ControlPlane.open(ws)
    try:
        co = plane.registry.get_company(res["company"])
        assert co["db_engine"] == "postgres" and co["status"] == "active"
        c = TestClient(create_app(auto_init=False, workspace=ws, plane=plane))
        assert c.post("/api/auth/login", json={"email": "boss@acme.ng", "password": res["password"]}).status_code == 200
        assert not [x for x in doctor.run_checks(ws) if x["status"] == "fail"]
    finally:
        plane.provisioning.drop_company(res["company"], root_password=PG_ROOT_PW)
        cfg = dict(plane.cfg)
        plane.dispose()
        dbadmin.drop_pg(cfg.get("db_host", "localhost"), int(cfg.get("db_port", 5432)), "postgres", PG_ROOT_PW, cfg["db_name"], cfg["db_user"])
