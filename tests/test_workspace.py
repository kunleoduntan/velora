"""The full developer journey: init → new-site → new-app → new-doctype → install-app → use it."""
import gzip
import json
from decimal import Decimal
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

import velora
from velora import site as site_mod
from velora.api import create_app
from velora.cli import main
from velora.meta.spec import DocType
from velora.workspace import Workspace

PG_ROOT_PW = os.environ.get("VELORA_TEST_PG_ROOT_PASSWORD")   # e.g. "velora" for postgres/postgres@localhost


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
    """Workspaces add apps to sys.path and import app packages; undo all of it after each test."""
    path_before, mods_before = list(sys.path), set(sys.modules)
    cwd = os.getcwd()
    yield
    os.chdir(cwd)
    site_mod.unload_all()
    velora.shutdown()
    sys.path[:] = path_before
    for name in set(sys.modules) - mods_before:
        f = getattr(sys.modules[name], "__file__", None) or ""
        if str(tmp_path) in f or str(tmp_path) in str(getattr(sys.modules[name], "__path__", "")):
            del sys.modules[name]


@pytest.fixture
def ws(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VELORA_SITE", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    assert main(["init", str(tmp_path / "ws")]) == 0
    monkeypatch.chdir(tmp_path / "ws")
    capsys.readouterr()
    return Workspace(tmp_path / "ws")


def cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def add_fields(ws, app, folder, fields, module="accounting"):
    p = ws.app_path(app) / app / module / "doctype" / folder / f"{folder}.json"
    d = json.loads(p.read_text())
    d["fields"].extend(fields)
    p.write_text(json.dumps(d, indent=2))


def make_app(ws, capsys, app="shop", doctype="Product", site=None, install=True, extra_fields=()):
    assert cli(capsys, "new-app", app, "--module", "Retail")[0] == 0
    assert cli(capsys, "new-doctype", doctype, "--app", app, "--module", "Retail")[0] == 0
    folder = doctype.lower().replace(" ", "_")
    add_fields(ws, app, folder, [{"fieldname": "price", "fieldtype": "Currency"}, *extra_fields], module="retail")
    if install:
        assert cli(capsys, "--site", site, "install-app", app)[0] == 0


# ---- init / sites -------------------------------------------------------------------------------
def test_init_creates_workspace_and_refuses_to_overwrite(ws, capsys):
    for d in ("apps", "config", "logs", "backups"):
        assert (ws.root / d).is_dir()
    assert not (ws.root / "sites").exists()                                                         # the legacy folder is not created for new installations
    assert (ws.root / "config" / "apps.txt").exists() and (ws.root / "config" / "common.json").exists()
    gi = (ws.root / ".gitignore").read_text()
    assert "/*" in gi and "!/apps" in gi and "sites/*/" not in gi                                    # everything but code is ignored: git add . can never publish master.key
    code, _, err = cli(capsys, "init", str(ws.root))
    assert code == 1 and "already a Velora workspace" in err


def test_commands_outside_a_workspace_explain_themselves(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    code, _, err = cli(capsys, "new-site", "x.local")
    assert code == 1 and "velora init" in err


def test_new_site_sqlite(ws, capsys):
    code, out, _ = cli(capsys, "new-site", "erp.local")
    assert code == 0 and "SQLite (development only)" in out
    cfg_file = ws.site_path("erp.local") / "site_config.json"
    assert oct(cfg_file.stat().st_mode & 0o777) == "0o600"                # holds secrets
    cfg = json.loads(cfg_file.read_text())
    assert cfg["db_type"] == "sqlite" and len(cfg["secret_key"]) >= 32 and cfg["developer_mode"] is False
    con = sqlite3.connect(ws.site_path("erp.local") / "site.db")
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"velora_installed_app", "velora_series", "velora_version"} <= tables
    assert ws.current_site() == "erp.local"                                # first site becomes the default
    assert (ws.site_path("erp.local") / "private" / "backups").is_dir()


@pytest.mark.parametrize("bad", ["../evil", "Erp Local", "a/b", ".hidden", "x" * 300, "UPPER.case", ""])
def test_site_names_are_validated(ws, capsys, bad):
    code, _, err = cli(capsys, "new-site", bad)
    assert code == 1 and "Invalid site name" in err
    assert ws.sites() == []


def test_duplicate_site_and_site_selection_errors(ws, capsys):
    cli(capsys, "new-site", "a.local")
    assert "already exists" in cli(capsys, "new-site", "a.local")[2]
    cli(capsys, "new-site", "b.local")
    code, _, err = cli(capsys, "install-app", "x")                          # no site chosen: the command applies to ALL sites, and the app is unknown to every one
    assert code == 1 and "'x' is not an app in this workspace" in err
    code, _, err = cli(capsys, "--site", "nope.local", "migrate")
    assert code == 1 and "does not exist" in err and "a.local" in err
    assert cli(capsys, "use", "b.local")[0] == 0 and ws.current_site() == "b.local"
    code, out, _ = cli(capsys, "list-sites")
    assert "* b.local" in out and "  a.local" in out


# ---- apps / doctypes ----------------------------------------------------------------------------
def test_new_app_scaffold_is_a_valid_importable_package(ws, capsys):
    assert cli(capsys, "new-app", "accounting")[0] == 0
    root = ws.app_path("accounting")
    for f in ("pyproject.toml", "README.md", "accounting/__init__.py", "accounting/hooks.py", "accounting/accounting/doctype/__init__.py"):
        assert (root / f).exists(), f
    assert ws.apps() == ["accounting"]
    ws.activate()
    import accounting.hooks as hooks   # noqa
    assert hooks.required_apps == [] and hooks.doc_events == {}
    for bad in ("Accounting", "1abc", "my-app", "a b"):
        assert cli(capsys, "new-app", bad)[0] == 1
    assert "already exists" in cli(capsys, "new-app", "accounting")[2]


def test_new_doctype_scaffolds_valid_metadata_and_scripts(ws, capsys):
    cli(capsys, "new-app", "accounting")
    assert cli(capsys, "new-doctype", "Journal Entry", "--app", "accounting", "--submittable")[0] == 0
    assert cli(capsys, "new-doctype", "Journal Entry Line", "--app", "accounting", "--child")[0] == 0
    base = ws.app_path("accounting") / "accounting" / "accounting" / "doctype"
    je = DocType.from_dict(json.loads((base / "journal_entry" / "journal_entry.json").read_text()))
    assert je.is_submittable and je.autoname == "series:JE-.####" and je.permissions[0].submit and je.permissions[0].export
    line = DocType.from_dict(json.loads((base / "journal_entry_line" / "journal_entry_line.json").read_text()))
    assert line.istable and not (base / "journal_entry_line" / "journal_entry_line.py").exists()
    assert "class JournalEntry(Document)" in (base / "journal_entry" / "journal_entry.py").read_text()
    assert 'velora.ui.form.on("Journal Entry"' in (base / "journal_entry" / "journal_entry.js").read_text()
    assert cli(capsys, "new-doctype", "Journal Entry", "--app", "accounting")[0] == 1          # duplicate
    assert cli(capsys, "new-doctype", "Bad/Name", "--app", "accounting")[0] == 1
    assert cli(capsys, "new-doctype", "X", "--app", "ghost")[0] == 1


# ---- the journey ---------------------------------------------------------------------------------
def test_full_journey_from_empty_directory_to_saved_document(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    make_app(ws, capsys, site="erp.local")
    code, out, _ = cli(capsys, "--site", "erp.local", "doctypes")
    assert "Product" in out
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        d = velora.new_doc("Product", title="Widget", price="19.99").insert()
        assert d.name == "P-0001"
        assert velora.get_doc("Product", d.name).price == Decimal("19.99")
    # change the DocType JSON, apply with migrate: the new column appears
    add_fields(ws, "shop", "product", [{"fieldname": "sku", "fieldtype": "Data", "unique": True}], module="retail")
    code, out, _ = cli(capsys, "--site", "erp.local", "migrate", "--dry-run")
    assert "ADD COLUMN" in out and "sku" in out and "dry run" in out
    code, out, _ = cli(capsys, "--site", "erp.local", "migrate")
    assert code == 0 and "ADD COLUMN" in out and "sku" in out
    assert "Nothing to migrate" in cli(capsys, "--site", "erp.local", "migrate")[1]      # idempotent
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert velora.new_doc("Product", title="Gadget", sku="G-1").insert().sku == "G-1"
    code, out, _ = cli(capsys, "list-apps")
    assert "shop" in out and "installed" in out


def test_install_twice_is_calm_and_an_unknown_app_is_refused(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    make_app(ws, capsys, site="erp.local")
    code, out, _ = cli(capsys, "--site", "erp.local", "install-app", "shop")                   # again: nothing to do, nothing wrong
    assert code == 0 and "already installed" in out and "installed on 0 of 1" in out
    code, _, err = cli(capsys, "--site", "erp.local", "install-app", "ghost")
    assert code == 1 and "'ghost' is not an app in this workspace" in err


# ---- multi-site isolation ------------------------------------------------------------------------
def test_sites_are_isolated_databases_with_their_own_apps(ws, capsys):
    cli(capsys, "new-site", "a.local")
    cli(capsys, "new-site", "b.local")
    make_app(ws, capsys, site="a.local")                       # installed on A only
    cli(capsys, "new-app", "other")
    cli(capsys, "new-doctype", "Note", "--app", "other")
    assert cli(capsys, "--site", "b.local", "install-app", "other")[0] == 0
    A, B = (site_mod.load_site(ws.site_path(n)) for n in ("a.local", "b.local"))
    with site_mod.use(A):
        velora.new_doc("Product", title="Only in A").insert()
        assert {d.name for d in velora.registry.all()} == {"Product"}
    with site_mod.use(B):
        assert {d.name for d in velora.registry.all()} == {"Note"}
        with pytest.raises(velora.exceptions.DoesNotExistError):
            velora.new_doc("Product", title="x")                # the DocType does not exist on B
        velora.new_doc("Note", title="Only in B").insert()
    assert A.db_url != B.db_url
    with site_mod.use(A):
        assert velora.get_list("Product", fields=["name"]) and len(velora.get_list("Product")) == 1
        assert not inspect(A.engine).has_table("tab_note")       # B's tables never appear in A's database
    with site_mod.use(B):
        assert not inspect(B.engine).has_table("tab_product")


def test_series_counters_are_per_site(ws, capsys):
    cli(capsys, "new-site", "a.local"); cli(capsys, "new-site", "b.local")
    make_app(ws, capsys, site="a.local")
    cli(capsys, "--site", "b.local", "install-app", "shop")
    A, B = (site_mod.load_site(ws.site_path(n)) for n in ("a.local", "b.local"))
    names = []
    for s in (A, A, B):
        with site_mod.use(s):
            names.append(velora.new_doc("Product", title="t").insert().name)
    assert names == ["P-0001", "P-0002", "P-0001"]


# ---- install safety ------------------------------------------------------------------------------
def test_install_with_invalid_metadata_changes_nothing(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    cli(capsys, "new-app", "broken")
    cli(capsys, "new-doctype", "Thing", "--app", "broken")
    add_fields(ws, "broken", "thing", [{"fieldname": "owner_link", "fieldtype": "Link", "options": "Nonexistent"}], module="broken")
    code, _, err = cli(capsys, "--site", "erp.local", "install-app", "broken")
    assert code == 1 and "Nonexistent" in err
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert site.installed_apps() == []
        assert not inspect(site.engine).has_table("tab_thing")


def test_after_install_hook_runs_in_the_site_and_failure_rolls_back(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    cli(capsys, "new-app", "seeded")
    cli(capsys, "new-doctype", "Setting Note", "--app", "seeded")
    root = ws.app_path("seeded") / "seeded"
    (root / "setup.py").write_text('''import velora
def after_install():
    velora.new_doc("Setting Note", title="created by after_install").insert()
def boom():
    raise RuntimeError("hook exploded")
''')
    hooks = (root / "hooks.py").read_text()
    (root / "hooks.py").write_text(hooks.replace("after_install = None", 'after_install = "seeded.setup.boom"'))
    code, _, err = cli(capsys, "--site", "erp.local", "install-app", "seeded")              # caught per site (so other sites continue), but the error keeps its type
    assert code == 1 and "RuntimeError: hook exploded" in err
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert site.installed_apps() == []                                  # not recorded as installed
    (root / "hooks.py").write_text(hooks.replace("after_install = None", 'after_install = "seeded.setup.after_install"'))
    sys.modules.pop("seeded.hooks", None)
    import importlib; importlib.invalidate_caches()
    assert cli(capsys, "--site", "erp.local", "install-app", "seeded")[0] == 0
    site_mod.unload_all()
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert [r["title"] for r in velora.get_list("Setting Note", fields=["title"])] == ["created by after_install"]


def test_required_apps_and_uninstall_rules(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    cli(capsys, "new-app", "base"); cli(capsys, "new-doctype", "Base Doc", "--app", "base")
    cli(capsys, "new-app", "vertical")
    h = ws.app_path("vertical") / "vertical" / "hooks.py"
    h.write_text(h.read_text().replace("required_apps = []", 'required_apps = ["base"]'))
    code, out, _ = cli(capsys, "--site", "erp.local", "install-app", "vertical")             # the app it needs is installed FIRST, by itself
    assert code == 0 and "(base, vertical)" in out
    code, _, err = cli(capsys, "--site", "erp.local", "uninstall-app", "base", "--yes")
    assert code == 1 and "vertical" in err and "needs it" in err and "Nothing was changed" in err
    assert "--yes" in cli(capsys, "--site", "erp.local", "uninstall-app", "vertical")[2]
    assert cli(capsys, "--site", "erp.local", "uninstall-app", "vertical", "--yes")[0] == 0
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert site.installed_apps() == ["base"]


def test_uninstall_keeps_data(ws, capsys):
    cli(capsys, "new-site", "erp.local")
    make_app(ws, capsys, site="erp.local")
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        velora.new_doc("Product", title="keep me").insert()
    assert cli(capsys, "--site", "erp.local", "uninstall-app", "shop", "--yes")[0] == 0
    with site_mod.use(site):
        assert "tab_product" in inspect(site.engine).get_table_names()
        with site.engine.connect() as c:
            assert c.execute(text("select title from tab_product")).scalar() == "keep me"


# ---- get-app --------------------------------------------------------------------------------------
def _git_repo(path: Path, package: str | None, doctype=True):
    path.mkdir(parents=True)
    if package:
        pkg = path / package / "mod" / "doctype" / "gadget"
        pkg.mkdir(parents=True)
        for d in (path / package, path / package / "mod", path / package / "mod" / "doctype", pkg):
            (d / "__init__.py").write_text('__version__ = "1.2.3"\n' if d == path / package else "")
        (pkg / "gadget.json").write_text(json.dumps({"name": "Gadget", "module": "Mod", "fields": [{"fieldname": "title", "fieldtype": "Data"}]}))
    (path / "README.md").write_text("x")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["git", "init", "-q"], ["git", "add", "."], ["git", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=path, env=env, check=True, capture_output=True)


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_get_app_from_git_then_install(ws, capsys, tmp_path):
    _git_repo(tmp_path / "remote" / "governmentone", "governmentone")
    cli(capsys, "new-site", "erp.local")
    code, out, err = cli(capsys, "get-app", str(tmp_path / "remote" / "governmentone"))
    assert code == 0, err
    assert ws.apps() == ["governmentone"] and (ws.app_path("governmentone") / "governmentone" / "__init__.py").exists()
    assert cli(capsys, "--site", "erp.local", "install-app", "governmentone")[0] == 0
    assert "1.2.3" in cli(capsys, "list-apps")[1]
    assert "already exists" in cli(capsys, "get-app", str(tmp_path / "remote" / "governmentone"))[2]


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_get_app_rejects_non_velora_repos_and_cleans_up(ws, capsys, tmp_path):
    _git_repo(tmp_path / "remote" / "notanapp", None)
    code, _, err = cli(capsys, "get-app", str(tmp_path / "remote" / "notanapp"))
    assert code == 1 and "not a Velora app" in err
    assert ws.apps() == [] and not ws.app_path("notanapp").exists()
    assert cli(capsys, "get-app", str(tmp_path / "nonexistent"))[0] == 1


# ---- backup / drop -------------------------------------------------------------------------------
def test_backup_and_drop_site(ws, capsys, tmp_path):
    cli(capsys, "new-site", "erp.local")
    make_app(ws, capsys, site="erp.local")
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        velora.new_doc("Product", title="backed up").insert()
    code, out, _ = cli(capsys, "backup")
    assert code == 0
    f = next((ws.site_path("erp.local") / "private" / "backups").glob("*.db.gz"))
    raw = tmp_path / "restored.db"
    raw.write_bytes(gzip.decompress(f.read_bytes()))
    assert sqlite3.connect(raw).execute("select title from tab_product").fetchone() == ("backed up",)
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert "--yes" in cli(capsys, "drop-site", "erp.local")[2]
    assert cli(capsys, "drop-site", "erp.local", "--yes")[0] == 0
    assert ws.sites() == [] and not (ws.sites_dir / "currentsite.txt").exists()


# ---- API: one process, many sites ------------------------------------------------------------------
@pytest.fixture
def two_site_client(ws, capsys):
    cli(capsys, "new-site", "a.local", "--developer-mode")
    cli(capsys, "new-site", "b.local", "--developer-mode")
    cli(capsys, "new-site", "closed.local")                                  # developer mode OFF
    make_app(ws, capsys, site="a.local")
    for s in ("b.local", "closed.local"):
        cli(capsys, "--site", s, "install-app", "shop")
    ws.activate()
    return TestClient(create_app(auto_init=False, workspace=ws))


H = {"X-Velora-User": "u", "X-Velora-Roles": "System Manager"}


def test_api_routes_each_request_to_the_site_named_by_the_host(two_site_client):
    c = two_site_client
    assert c.post("/api/resource/Product", json={"title": "from A"}, headers={**H, "Host": "a.local"}).status_code == 201
    assert c.post("/api/resource/Product", json={"title": "from B1"}, headers={**H, "Host": "b.local"}).status_code == 201
    assert c.post("/api/resource/Product", json={"title": "from B2"}, headers={**H, "Host": "b.local:8000"}).status_code == 201   # port ignored
    titles = lambda host: sorted(r["title"] for r in c.get("/api/resource/Product", params={"fields": '["title"]'}, headers={**H, "Host": host}).json()["data"])
    assert titles("a.local") == ["from A"]
    assert titles("b.local") == ["from B1", "from B2"]


def test_api_unknown_hosts_and_traversal_attempts_never_reach_a_site(two_site_client):
    c = two_site_client
    for host in ("nope.example.com", "..", "../a.local", "a.local/../b.local", "a.local%2f..", "A.LOCAL.evil"):
        r = c.get("/api/doctypes", headers={**H, "Host": host})
        assert r.status_code == 404 and r.json()["error"] == "SiteNotFound", host
    assert c.get("/api/doctypes", headers={**H, "Host": "A.Local"}).status_code == 200      # host matching is case-insensitive


def test_api_default_site_is_opt_in_for_hosts_like_a_bare_ip(two_site_client, ws):
    c = two_site_client
    assert c.get("/api/doctypes", headers={**H, "Host": "203.0.113.7"}).status_code == 404         # unknown host: refused by default
    cfg = ws.common_config_file
    cfg.write_text(json.dumps({"default_site": "b.local"}))
    assert c.get("/api/doctypes", headers={**H, "Host": "203.0.113.7:8000"}).status_code == 200
    assert c.get("/api/doctypes", headers={**H, "Host": "[::1]:8000"}).status_code == 200            # loopback IPv6
    assert c.get("/api/doctypes", headers={**H, "Host": ".."}).status_code == 404                   # malformed is never served


def test_api_loopback_uses_current_site_and_developer_mode_is_per_site(two_site_client, ws):
    c = two_site_client
    ws.use("a.local")
    assert c.get("/api/doctypes", headers={**H, "Host": "localhost:8000"}).status_code == 200
    r = c.get("/api/doctypes", headers={**H, "Host": "closed.local"})
    assert r.status_code == 401 and r.json()["error"] == "AuthenticationRequired"          # this site has developer mode off


def test_api_forced_site_overrides_host(ws, capsys):
    cli(capsys, "new-site", "a.local", "--developer-mode"); cli(capsys, "new-site", "b.local", "--developer-mode")
    make_app(ws, capsys, site="a.local")
    ws.activate()
    c = TestClient(create_app(auto_init=False, workspace=ws, site="a.local"))
    assert c.post("/api/resource/Product", json={"title": "x"}, headers={**H, "Host": "anything.example"}).status_code == 201


def test_api_unloadable_site_returns_503_not_a_crash(ws, capsys):
    cli(capsys, "new-site", "a.local", "--developer-mode")
    cfg = ws.site_path("a.local") / "site_config.json"
    d = json.loads(cfg.read_text()); d.update(db_type="postgres", db_user="x", db_password="y", db_name="z", db_host="127.0.0.1", db_port=1)
    cfg.write_text(json.dumps(d))
    c = TestClient(create_app(auto_init=False, workspace=ws))
    r = c.get("/api/doctypes", headers={**H, "Host": "a.local"})
    assert r.status_code == 503 and r.json()["error"] == "SiteUnavailable"


# ---- PostgreSQL: provisioning, bring-your-own database, transactional install ----------------------
pg = pytest.mark.skipif(not PG_ROOT_PW, reason="set VELORA_TEST_PG_ROOT_PASSWORD to test PostgreSQL provisioning")


def _root():
    from sqlalchemy import create_engine
    return create_engine(f"postgresql+psycopg://postgres:{PG_ROOT_PW}@localhost/postgres", isolation_level="AUTOCOMMIT")


@pg
def test_pg_provision_install_backup_and_drop(ws, capsys):
    code, out, err = cli(capsys, "new-site", "erp.local", "--db-root-password", PG_ROOT_PW)
    assert code == 0, err
    cfg = json.loads((ws.site_path("erp.local") / "site_config.json").read_text())
    assert cfg["db_type"] == "postgres" and cfg["provisioned_db"] and cfg["db_user"] == cfg["db_name"] and len(cfg["db_password"]) >= 24
    root = _root()
    with root.connect() as c:
        assert c.execute(text("select 1 from pg_database where datname=:n"), {"n": cfg["db_name"]}).scalar() == 1
    make_app(ws, capsys, site="erp.local")
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        velora.new_doc("Product", title="in pg").insert()
    code, out, err = cli(capsys, "backup")
    assert code == 0, err
    dump = gzip.decompress(next((ws.site_path("erp.local") / "private" / "backups").glob("*.sql.gz")).read_bytes()).decode()
    assert "CREATE TABLE public.tab_product" in dump and "in pg" in dump
    assert "root-password" in cli(capsys, "drop-site", "erp.local", "--yes")[2]       # refuses without root creds
    assert cli(capsys, "drop-site", "erp.local", "--yes", "--db-root-password", PG_ROOT_PW)[0] == 0
    with root.connect() as c:
        assert c.execute(text("select 1 from pg_database where datname=:n"), {"n": cfg["db_name"]}).first() is None
        assert c.execute(text("select 1 from pg_roles where rolname=:n"), {"n": cfg["db_user"]}).first() is None
    root.dispose()


@pg
def test_pg_bring_your_own_database_like_managed_hosting(ws, capsys):
    root = _root()
    with root.connect() as c:                                   # what a hosting control panel does for you
        c.exec_driver_sql("DROP DATABASE IF EXISTS byo_db WITH (FORCE)")
        c.exec_driver_sql("DROP ROLE IF EXISTS byo_user")
        c.exec_driver_sql("CREATE ROLE byo_user LOGIN PASSWORD 'byo_pw'")
        c.exec_driver_sql("CREATE DATABASE byo_db OWNER byo_user")
    code, _, err = cli(capsys, "new-site", "erp.local", "--db", "postgres", "--db-name", "byo_db", "--db-user", "byo_user", "--db-password", "wrong")
    assert code == 1 and "Cannot connect" in err and not ws.site_path("erp.local").exists()
    assert cli(capsys, "new-site", "erp.local", "--db-name", "byo_db", "--db-user", "byo_user", "--db-password", "byo_pw")[0] == 0
    assert "--db-root-password" in cli(capsys, "new-site", "x.local", "--db", "postgres")[2]
    out = cli(capsys, "drop-site", "erp.local", "--yes")
    assert "NOT dropped" in out[1]                              # never drops a database Velora did not create
    with root.connect() as c:
        assert c.execute(text("select 1 from pg_database where datname='byo_db'")).scalar() == 1
        c.exec_driver_sql("DROP DATABASE byo_db WITH (FORCE)")
        c.exec_driver_sql("DROP ROLE byo_user")
    root.dispose()


@pg
def test_pg_failed_install_rolls_back_tables_too(ws, capsys):
    cli(capsys, "new-site", "erp.local", "--db-root-password", PG_ROOT_PW)
    cli(capsys, "new-app", "seeded"); cli(capsys, "new-doctype", "Setting Note", "--app", "seeded")
    root = ws.app_path("seeded") / "seeded"
    (root / "setup.py").write_text("def boom():\n    raise RuntimeError('hook exploded')\n")
    h = (root / "hooks.py"); h.write_text(h.read_text().replace("after_install = None", 'after_install = "seeded.setup.boom"'))
    code, _, err = cli(capsys, "--site", "erp.local", "install-app", "seeded")
    assert code == 1 and "RuntimeError: hook exploded" in err
    site = site_mod.load_site(ws.site_path("erp.local"))
    with site_mod.use(site):
        assert site.installed_apps() == []
        assert not inspect(site.engine).has_table("tab_setting_note")       # PostgreSQL DDL is transactional: nothing left behind
    cli(capsys, "drop-site", "erp.local", "--yes", "--db-root-password", PG_ROOT_PW)


def test_workspace_shortcuts_accept_company_settings_pages():
    from velora.application_workspaces import _clean_widget
    item = _clean_widget({"type": "shortcut", "title": "Company Setup Readiness",
                          "route": "#/settings/company-setup", "width": 2})
    assert item["route"] == "#/settings/company-setup"


def test_workspace_shortcuts_accept_hr_employee_360_routes():
    from velora.application_workspaces import _clean_widget
    item = _clean_widget({"type": "shortcut", "title": "Employee 360°",
                          "route": "#/hr/employee/EMP-0001", "width": 2})
    assert item["route"] == "#/hr/employee/EMP-0001"
