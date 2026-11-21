"""Control plane: identity, company registry, database-per-company routing, provisioning."""
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

import velora
from velora import site as site_mod
from velora.api import create_app
from velora.cli import main
from velora.controlplane import ControlPlane, identity as idmod, models as cpm
from velora.controlplane.secrets import SecretStore, generate_master_key
from velora.exceptions import (AuthenticationRequired, CompanyAccessDenied, CompanyUnavailable, ValidationError)
from velora.scaffold import new_app, new_doctype
from velora.workspace import Workspace, WorkspaceError

PG_ROOT_PW = os.environ.get("VELORA_TEST_PG_ROOT_PASSWORD")
PW = "correct horse battery"


@pytest.fixture(autouse=True)
def clean_state(tmp_path):
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


def make_app(ws, name="shop", doctype="Product", fail_install=False):
    root = new_app(ws.apps_dir, name, module="Retail")
    ws.register_app(name)
    d = new_doctype(root, name, doctype, module="Retail")
    p = d / f"{d.name}.json"
    spec = json.loads(p.read_text())
    spec["fields"].append({"fieldname": "price", "fieldtype": "Currency", "in_list_view": True})
    spec["permissions"].append({"role": "Sales User", "read": True, "write": True, "create": True})
    p.write_text(json.dumps(spec, indent=2))
    if fail_install:
        (root / name / "setup.py").write_text("def boom():\n    raise RuntimeError('install hook exploded')\n")
        h = root / name / "hooks.py"
        h.write_text(h.read_text().replace("after_install = None", f'after_install = "{name}.setup.boom"'))
    return root


@pytest.fixture
def plat(tmp_path, monkeypatch):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("Enterprise Group")
    A = plane.provisioning.provision_company("Enterprise Group", "Velora Technologies", apps=["shop"])
    B = plane.provisioning.provision_company("Enterprise Group", "Value Impacts Consulting", apps=["shop"])
    idn = plane.identity
    idn.create_user("alice@example.com", "Alice", PW)
    idn.create_user("bob@example.com", "Bob", PW)
    idn.create_user("carol@example.com", "Carol", PW)
    idn.grant("alice@example.com", A["id"], ["System Manager"])
    idn.grant("alice@example.com", B["id"], ["Sales User"])          # different role in the other company
    idn.grant("bob@example.com", B["id"], ["System Manager"])
    ns = type("NS", (), {})()
    ns.ws, ns.plane, ns.A, ns.B = ws, plane, A["id"], B["id"]
    ns.client = lambda **kw: TestClient(create_app(auto_init=False, workspace=ws, plane=plane), **kw)
    yield ns
    plane.dispose()


H = {"X-Velora-Request": "1"}


def login(c, email="alice@example.com", pw=PW, **extra):
    return c.post("/api/auth/login", json={"email": email, "password": pw, **extra})


def hdr(company):
    return {**H, "X-Velora-Company": company}


# ============================ bootstrap / secrets =================================================
def test_platform_init_creates_control_plane_with_protected_files(plat):
    pdir = plat.ws.root / "platform"
    for f in ("control_plane.json", "master.key"):
        assert oct((pdir / f).stat().st_mode & 0o777) == "0o600", f
    tables = set(inspect(plat.plane.engine).get_table_names())
    assert {"cp_tenant", "cp_company", "cp_user", "cp_user_company", "cp_session", "cp_secret", "cp_audit"} <= tables
    root = plat.plane.identity.get_user("root@example.com")
    assert root["is_platform_admin"] is True
    with pytest.raises(WorkspaceError, match="already has a control plane"):
        ControlPlane.create(plat.ws)


def test_failed_platform_init_leaves_nothing_behind(tmp_path):
    ws = Workspace.create(tmp_path / "w2")
    with pytest.raises(ValidationError, match="at least 10"):
        ControlPlane.create(ws, admin_email="a@b.com", admin_password="short")
    assert not (ws.root / "platform" / "control_plane.json").exists() and not (ws.root / "platform" / "master.key").exists()


def test_secret_store_never_keeps_plaintext_and_needs_the_master_key(plat, tmp_path, monkeypatch):
    ref = plat.plane.secrets.put("s3cret-db-password")
    assert ref.startswith("local:")
    with plat.plane.engine.connect() as c:
        cipher = c.execute(select(cpm.secret.c.ciphertext).where(cpm.secret.c.ref == ref)).scalar_one()
    assert "s3cret" not in cipher and plat.plane.secrets.get(ref) == "s3cret-db-password"
    wrong = SecretStore(generate_master_key(), plat.plane.engine)
    with pytest.raises(WorkspaceError, match="wrong master key"):
        wrong.get(ref)
    monkeypatch.setenv("MY_PG_PW", "from-env")
    f = tmp_path / "pw.txt"; f.write_text("from-file\n")
    assert plat.plane.secrets.get("env:MY_PG_PW") == "from-env" and plat.plane.secrets.get(f"file:{f}") == "from-file"
    with pytest.raises(WorkspaceError):
        plat.plane.secrets.get("env:NOT_SET_ANYWHERE")
    with pytest.raises(WorkspaceError, match="Unknown secret"):
        plat.plane.secrets.get("vault:x")
    plat.plane.secrets.delete(ref)
    with pytest.raises(WorkspaceError, match="does not exist"):
        plat.plane.secrets.get(ref)


# ============================ passwords / sign-in =================================================
def test_password_hashing_is_salted_scrypt_and_verifies():
    h1, h2 = idmod.hash_password(PW), idmod.hash_password(PW)
    assert h1 != h2 and h1.startswith("scrypt$") and PW not in h1          # unique salt each time, parameters stored
    assert idmod.verify_password(PW, h1) and not idmod.verify_password(PW + "x", h1)
    assert not idmod.verify_password(PW, "garbage") and not idmod.verify_password(PW, "md5$1$2$3$4$5")


@pytest.mark.parametrize("pw,msg", [("short", "at least 10"), ("x" * 300, "at most 256"), ("new@example.com", "same as the email")])
def test_password_policy(plat, pw, msg):
    with pytest.raises(ValidationError, match=msg):
        plat.plane.identity.create_user("new@example.com", "New", pw)


def test_login_branding_is_public_and_resolves_registered_company_domain(plat):
    from velora.company import CompanyInfo, company_context
    from velora.controlplane.directory import PlaneDirectory
    from velora.settings import set_setting

    plat.plane.registry.add_domain("velora-login.example.com", plat.A, primary=True, locked=True)
    company = plat.plane.registry.get_company(plat.A)
    tenant = plat.plane.registry.get_tenant(company["tenant_id"])
    site = plat.plane.router.site_for(company)
    info = CompanyInfo(company["id"], company["name"], company["tenant_id"], tenant["name"], PlaneDirectory(plat.plane, company["id"]))
    with site_mod.use(site), company_context(info):
        set_setting("application.branding", {"app_name": "Velora Demo", "tagline": "Business, beautifully organised.", "logo_url": "/files/brand-mark.svg"})

    response = plat.client().get("/api/auth/login-branding", headers={"host": "velora-login.example.com"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {"app_name": "Velora Demo", "tagline": "Business, beautifully organised.", "logo_url": "/files/brand-mark.svg"}


def test_login_branding_uses_configured_velora_identity_on_unbound_domains(plat, monkeypatch):
    monkeypatch.setenv("VELORA_LOGIN_BRAND_NAME", "Velora Group")
    monkeypatch.setenv("VELORA_LOGIN_TAGLINE", "One connected enterprise.")
    monkeypatch.setenv("VELORA_LOGIN_LOGO_URL", "/assets/velora-logo.svg")
    response = plat.client().get("/api/auth/login-branding", headers={"host": "main.example.com"})
    assert response.status_code == 200
    assert response.json()["data"] == {
        "app_name": "Velora Group", "tagline": "One connected enterprise.", "logo_url": "/assets/velora-logo.svg"
    }


def test_login_success_and_tokens_are_stored_hashed(plat):
    r = plat.plane.identity.authenticate("Alice@Example.com ", PW)         # email is case/space-insensitive
    assert r.context.email == "alice@example.com" and len(r.token) >= 40
    with plat.plane.engine.connect() as c:
        stored = c.execute(select(cpm.session.c.token_hash)).scalars().all()
    assert r.token not in stored and idmod._token_hash(r.token) in stored   # a leaked database cannot be replayed


def test_failed_logins_are_indistinguishable_and_never_say_which_part_was_wrong(plat):
    idn = plat.plane.identity
    msgs = set()
    for email, pw in [("alice@example.com", "wrong-password-1"), ("nobody@example.com", PW), ("not-an-email", PW), ("", ""), ("alice@example.com", "x" * 5000)]:
        with pytest.raises(AuthenticationRequired) as e:
            idn.authenticate(email, pw)
        msgs.add(str(e.value))
    assert msgs == {"Invalid email or password"}


def test_lockout_after_repeated_failures_then_recovers(plat, monkeypatch):
    idn = plat.plane.identity
    for _ in range(idmod.MAX_FAILED):
        with pytest.raises(AuthenticationRequired):
            idn.authenticate("bob@example.com", "wrong-password-x")
    with pytest.raises(AuthenticationRequired, match="temporarily locked"):
        idn.authenticate("bob@example.com", PW)                              # even the right password is refused while locked
    real = idmod._now
    monkeypatch.setattr(idmod, "_now", lambda: real() + timedelta(minutes=idmod.LOCK_MINUTES + 1))
    assert idn.authenticate("bob@example.com", PW).context.email == "bob@example.com"
    assert idn.get_user("bob@example.com")["failed_attempts"] == 0


def test_inactive_user_cannot_sign_in_and_loses_sessions(plat):
    idn = plat.plane.identity
    tok = idn.authenticate("carol@example.com", PW).token
    idn.set_active("carol@example.com", False)
    with pytest.raises(AuthenticationRequired):
        idn.resolve(tok)
    with pytest.raises(AuthenticationRequired, match="Invalid email or password"):
        idn.authenticate("carol@example.com", PW)


def test_sessions_expire_slide_and_have_a_hard_cap(plat, monkeypatch):
    idn = plat.plane.identity
    tok = idn.authenticate("alice@example.com", PW).token
    real = idmod._now
    monkeypatch.setattr(idmod, "_now", lambda: real() + timedelta(hours=11))
    assert idn.resolve(tok).email == "alice@example.com"                    # still valid, and this use slides the expiry
    monkeypatch.setattr(idmod, "_now", lambda: real() + timedelta(hours=22))
    assert idn.resolve(tok).email == "alice@example.com"                    # 22h after login but only 11h idle
    monkeypatch.setattr(idmod, "_now", lambda: real() + timedelta(hours=40))
    with pytest.raises(AuthenticationRequired, match="expired"):
        idn.resolve(tok)
    monkeypatch.setattr(idmod, "_now", real)                                # back to the real clock before creating the next session
    tok2 = idn.authenticate("alice@example.com", PW).token
    for d in range(1, 30):                                                  # kept alive by activity every 10h, until the 7-day cap
        monkeypatch.setattr(idmod, "_now", lambda d=d: real() + timedelta(hours=10 * d))
        try:
            idn.resolve(tok2)
        except AuthenticationRequired:
            break
    else:
        pytest.fail("session survived past the hard cap")
    assert d * 10 >= 7 * 24 and (d - 1) * 10 < 7 * 24                       # alive right up to 7 days, refused after


def test_logout_tampered_token_and_password_change_revoke_access(plat):
    idn = plat.plane.identity
    tok = idn.authenticate("alice@example.com", PW).token
    with pytest.raises(AuthenticationRequired):
        idn.resolve(tok[:-2] + "xx")
    with pytest.raises(AuthenticationRequired):
        idn.resolve(None)
    idn.logout(tok)
    with pytest.raises(AuthenticationRequired):
        idn.resolve(tok)
    t1, t2 = (idn.authenticate("alice@example.com", PW).token for _ in range(2))
    ctx = idn.resolve(t1)
    with pytest.raises(AuthenticationRequired, match="Current password"):
        idn.change_password(ctx, "nope-nope-nope", "a brand new passphrase")
    idn.change_password(ctx, PW, "a brand new passphrase")
    for t in (t1, t2):
        with pytest.raises(AuthenticationRequired):
            idn.resolve(t)
    assert idn.authenticate("alice@example.com", "a brand new passphrase")


def test_security_events_are_audited(plat):
    idn = plat.plane.identity
    with pytest.raises(AuthenticationRequired):
        idn.authenticate("alice@example.com", "wrong-password-1")
    idn.authenticate("alice@example.com", PW)
    with plat.plane.engine.connect() as c:
        events = c.execute(select(cpm.audit.c.event)).scalars().all()
    assert {"login.failed", "login.ok", "access.grant", "company.provision", "tenant.create", "user.create", "platform.init"} <= set(events)
    with plat.plane.engine.connect() as c:                                   # failures record the reason but never the password
        blob = json.dumps([dict(r) for r in c.execute(select(cpm.audit.c.subject, cpm.audit.c.detail)).mappings()], default=str)
    assert "wrong-password-1" not in blob


# ============================ company access ====================================================
def test_companies_and_roles_are_per_user_and_per_company(plat):
    idn = plat.plane.identity
    uid = idn.get_user("alice@example.com")["id"]
    mine = {c["id"]: c["roles"] for c in idn.companies_for(uid)}
    assert mine == {plat.A: ["System Manager"], plat.B: ["Sales User"]}
    assert idn.companies_for(idn.get_user("carol@example.com")["id"]) == []


def test_authorize_never_reveals_whether_a_company_exists(plat):
    idn = plat.plane.identity
    tok = idn.authenticate("bob@example.com", PW).token
    auth = idn.resolve(tok)
    msgs = set()
    for cid in (plat.A, "COMP-999", "nonsense"):                             # bob is not in A; 999 and nonsense do not exist
        with pytest.raises(CompanyAccessDenied) as e:
            idn.authorize(auth, cid)
        msgs.add(str(e.value))
    assert msgs == {"You do not have access to this company"}
    co, roles = idn.authorize(auth, None)                                    # bob has exactly one company: used by default
    assert co["id"] == plat.B and roles == ["System Manager"]


def test_user_without_companies_and_ambiguous_choice_get_clear_errors(plat):
    idn = plat.plane.identity
    carol = idn.resolve(idn.authenticate("carol@example.com", PW).token)
    with pytest.raises(CompanyAccessDenied, match="not been given access"):
        idn.authorize(carol, None)
    alice = idn.resolve(idn.authenticate("alice@example.com", PW).token)
    with pytest.raises(CompanyAccessDenied, match="Select a company"):
        idn.authorize(alice, None)                                           # two companies, none chosen


def test_revoke_and_suspend(plat):
    idn, reg = plat.plane.identity, plat.plane.registry
    alice = idn.resolve(idn.authenticate("alice@example.com", PW).token)
    idn.switch_company(alice, plat.A)
    reg.set_status(plat.A, "suspended")
    with pytest.raises(CompanyUnavailable, match="suspended"):
        idn.authorize(alice, plat.A)
    reg.set_status(plat.A, "active")
    assert idn.authorize(alice, plat.A)[0]["id"] == plat.A
    idn.revoke("alice@example.com", plat.A)
    with pytest.raises(CompanyAccessDenied):
        idn.authorize(alice, plat.A)


# ============================ routing / isolation ================================================
def test_each_company_has_its_own_database_apps_and_numbering(plat):
    plane = plat.plane
    with plane.company_scope(plat.A):
        a = velora.new_doc("Product", title="Customer 001").insert()
        assert velora.current_company().id == plat.A
    with plane.company_scope(plat.B):
        b = velora.new_doc("Product", title="Customer 001").insert()          # the SAME name in another company
        assert velora.current_company().name == "Value Impacts Consulting"
    assert a.name == b.name == "P-0001"                                       # numbering sequences are independent
    sa, sb = (plane.router.site_for(plane.registry.get_company(c)) for c in (plat.A, plat.B))
    assert sa is not sb and sa.db_url != sb.db_url
    with site_mod.use(sa):
        assert len(velora.get_list("Product")) == 1
    with site_mod.use(sb):
        assert len(velora.get_list("Product")) == 1
    assert velora.current_company() is None                                   # nothing leaked out of the scope


def test_router_caches_evicts_and_notices_apps_installed_elsewhere(plat):
    from velora.controlplane.router import DatabaseRouter
    plane = plat.plane
    a, b = plane.registry.get_company(plat.A), plane.registry.get_company(plat.B)
    small = DatabaseRouter(plane, max_pools=1)
    sa = small.site_for(a)
    assert small.site_for(a) is sa                                           # cached: one pool per company, reused
    small.site_for(b)
    assert small.active_pools() == [plat.B] and sa._engine is None           # LRU evicted A and released its pool
    router = plane.router
    s1 = router.site_for(a)
    # another process installs an app into company A's database
    make_app(plat.ws, "extra", "Gadget")
    other = site_mod.Site("elsewhere", router.db_url(a))
    from velora import apps as apps_mod
    apps_mod.install_app(plat.ws, other, "extra")
    assert "Gadget" not in {d.name for d in s1.registry.all()}
    router.refresh_seconds = 0
    assert "Gadget" in {d.name for d in router.site_for(a).registry.all()}     # picked up without restarting the server


def test_company_database_never_holds_the_control_plane_data(plat):
    plane = plat.plane
    site = plane.router.site_for(plane.registry.get_company(plat.A))
    names = set(inspect(site.engine).get_table_names())
    assert "tab_product" in names and not any(n.startswith("cp_") for n in names)   # identity/registry live only in the control plane


# ============================ provisioning =====================================================
def test_provisioned_company_is_active_with_apps_and_version(plat):
    co = plat.plane.registry.get_company(plat.A)
    assert co["status"] == "active" and co["provisioning_status"] == "ready" and co["schema_version"] == velora.__version__
    assert co["secret_ref"] is None and plat.plane.sqlite_path(co).exists() and co["provisioned_db"] in (False, 0)
    assert plat.plane.registry.list_companies()[0]["tenant_name"] == "Enterprise Group"


def test_failed_provisioning_is_recorded_and_cleaned_up(plat):
    make_app(plat.ws, "bad", "Thing", fail_install=True)
    with pytest.raises(RuntimeError, match="install hook exploded"):
        plat.plane.provisioning.provision_company("Enterprise Group", "Doomed Co", apps=["bad"])
    co = next(c for c in plat.plane.registry.list_companies() if c["name"] == "Doomed Co")
    assert co["status"] == "failed" and "install hook exploded" in co["provisioning_error"]
    assert not plat.plane.sqlite_path(co).exists()                            # the half-built database is gone (looked up where it WOULD be, so this is a real check)
    with pytest.raises(ValidationError, match="failed"):
        plat.plane.registry.set_status(co["id"], "active")
    assert plat.plane.registry.get_company(co["id"])["id"] == co["id"]
    plat.plane.provisioning.drop_company(co["id"])
    assert plat.plane.registry.get_company(co["id"]) is None


def test_provisioning_validates_inputs(plat):
    p = plat.plane.provisioning
    with pytest.raises(ValidationError, match="No such tenant"):
        p.provision_company("Nope", "X")
    with pytest.raises(WorkspaceError, match="Not in this workspace"):
        p.provision_company("Enterprise Group", "X", apps=["ghost"])
    with pytest.raises(WorkspaceError, match="root-password"):
        p.provision_company("Enterprise Group", "X", db="postgres")
    with pytest.raises(ValidationError, match="already exists"):
        p.provision_company("Enterprise Group", "Velora Technologies")
    assert [c["name"] for c in plat.plane.registry.list_companies()] == ["Velora Technologies", "Value Impacts Consulting"]   # failed attempts left no rows


def test_drop_company_removes_access_and_database(plat):
    path = plat.plane.sqlite_path(plat.plane.registry.get_company(plat.B))
    note = plat.plane.provisioning.drop_company(plat.B)
    assert "deleted" in note and not path.exists()
    assert plat.plane.registry.get_company(plat.B) is None
    uid = plat.plane.identity.get_user("bob@example.com")["id"]
    assert plat.plane.identity.companies_for(uid) == []


def test_migrate_all_rolls_through_every_company_and_survives_one_failure(plat):
    results = {r["company"]: r for r in plat.plane.migrate_all()}
    assert results[plat.A]["plan"] == [] and results[plat.B]["plan"] == []
    broken = plat.plane.sqlite_path(plat.plane.registry.get_company(plat.B))
    for side in ("-wal", "-shm"):                                   # (a WAL database keeps its recent pages beside the file: remove them so the file really is garbage)
        broken.with_name(broken.name + side).unlink(missing_ok=True)
    junk = broken.with_name(broken.name + ".junk")
    junk.write_bytes(b"not a database")
    junk.replace(broken)                                                 # corrupt B (a NEW file, so connections still open on the old one cannot hide it)
    plat.plane.router.forget(plat.B)
    results = {r["company"]: r for r in plat.plane.migrate_all()}
    assert "plan" in results[plat.A] and "error" in results[plat.B]               # A still migrated


# ============================ API ==============================================================
def test_login_cookie_flags_and_profile(plat):
    c = plat.client()
    r = login(c)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie
    data = r.json()["data"]
    assert data["user"]["email"] == "alice@example.com" and "token" not in data and "password" not in json.dumps(data)
    assert {x["id"] for x in data["companies"]} == {plat.A, plat.B} and data["active_company"] is None
    r = plat.client().post("/api/auth/login", json={"email": "alice@example.com", "password": PW}, headers={"X-Forwarded-Proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()                                  # behind a TLS-terminating proxy


def test_api_requires_sign_in_and_a_company(plat):
    c = plat.client()
    r = c.get("/api/doctypes")
    assert r.status_code == 401 and r.json()["error"] == "AuthenticationRequired"
    assert c.get("/api/auth/config").json()["data"]["mode"] == "password"
    login(c)
    r = c.get("/api/doctypes")                                                   # alice has two companies and picked none
    assert r.status_code == 403 and "Select a company" in r.json()["message"]
    r = c.get("/api/doctypes", headers=hdr(plat.A))
    assert r.status_code == 200 and [d["name"] for d in r.json()["data"]] == ["Product"]
    bad = c.get("/api/doctypes", headers=hdr(plat.A.replace("001", "777")))
    assert bad.status_code == 403 and bad.json()["error"] == "CompanyAccessDenied"


def test_csrf_header_is_required_for_cookie_sessions_but_not_bearer(plat):
    c = plat.client()
    login(c)
    body = {"title": "csrf"}
    r = c.post("/api/resource/Product", json=body, headers={"X-Velora-Company": plat.A})          # cookie, no custom header
    assert r.status_code == 403 and "X-Velora-Request" in r.json()["message"]
    assert c.post("/api/resource/Product", json=body, headers=hdr(plat.A)).status_code == 201
    assert c.post("/api/auth/logout").status_code == 403                                           # logout needs it too
    tok = login(plat.client(), return_token=True).json()["data"]["token"]
    api = plat.client()
    r = api.post("/api/resource/Product", json=body, headers={"Authorization": f"Bearer {tok}", "X-Velora-Company": plat.A})
    assert r.status_code == 201                                                                    # Bearer is not CSRF-exposed


def test_switching_company_needs_no_new_sign_in_and_data_stays_separate(plat):
    c = plat.client()
    login(c)
    for cid, title in ((plat.A, "Customer 001"), (plat.B, "Customer 001")):
        r = c.post("/api/resource/Product", json={"title": title}, headers=hdr(cid))
        assert r.status_code == 201 and r.json()["data"]["name"] == "P-0001"
    assert c.post("/api/auth/switch-company", json={"company_id": plat.B}, headers=H).json()["data"]["id"] == plat.B
    me = c.get("/api/auth/me").json()["data"]                                       # session default is now B ...
    assert me["active_company"] == plat.B
    listing = lambda cid: c.get("/api/resource/Product", headers={"X-Velora-Company": cid}).json()["data"]
    assert len(listing(plat.A)) == 1 and len(listing(plat.B)) == 1                  # ... and the header still picks per request (tabs)
    c.post("/api/resource/Product", json={"title": "only B"}, headers=H)             # no header: session default (B)
    assert len(listing(plat.A)) == 1 and len(listing(plat.B)) == 2
    denied = c.post("/api/auth/switch-company", json={"company_id": "COMP-404"}, headers=H)
    assert denied.status_code == 403


def test_roles_are_enforced_per_company(plat):
    c = plat.client()
    login(c)
    pa = c.post("/api/resource/Product", json={"title": "a"}, headers=hdr(plat.A)).json()["data"]["name"]
    pb = c.post("/api/resource/Product", json={"title": "b"}, headers=hdr(plat.B)).json()["data"]["name"]
    # alice is System Manager in A (may export + delete) but only Sales User in B (may not)
    assert c.post("/api/export/Product", json={}, headers=hdr(plat.A)).status_code == 200
    r = c.post("/api/export/Product", json={}, headers=hdr(plat.B))
    assert r.status_code == 403 and "export" in r.json()["message"]
    assert c.delete(f"/api/resource/Product/{pb}", headers=hdr(plat.B)).status_code == 403
    assert c.delete(f"/api/resource/Product/{pa}", headers=hdr(plat.A)).status_code == 200
    meta_a = c.get("/api/meta/Product", headers=hdr(plat.A)).json()["data"]["permissions"]
    meta_b = c.get("/api/meta/Product", headers=hdr(plat.B)).json()["data"]["permissions"]
    assert meta_a["delete"] is True and meta_b["delete"] is False and meta_b["write"] is True


def test_suspended_company_and_sign_out(plat):
    c = plat.client()
    login(c)
    plat.plane.registry.set_status(plat.A, "suspended")
    r = c.get("/api/doctypes", headers=hdr(plat.A))
    assert r.status_code == 423 and "suspended" in r.json()["message"]
    assert c.get("/api/doctypes", headers=hdr(plat.B)).status_code == 200            # other company unaffected
    assert c.post("/api/auth/logout", headers=H).status_code == 200
    assert c.get("/api/doctypes", headers=hdr(plat.B)).status_code == 401


def test_unreachable_company_database_returns_503_and_is_audited(plat):
    c = plat.client()
    login(c)
    co = plat.plane.registry.get_company(plat.A)
    plat.plane.sqlite_path(co).unlink()
    plat.plane.router.forget(plat.A)
    plat.plane.registry.update_company(plat.A, db_name="/nonexistent-dir/x.db")
    r = c.get("/api/doctypes", headers=hdr(plat.A))
    assert r.status_code == 503 and r.json()["error"] == "ServiceUnavailable"
    assert "nonexistent" not in r.text                                               # internals are not leaked to the client
    assert c.get("/api/doctypes", headers=hdr(plat.B)).status_code == 200


def test_change_password_over_api_signs_everyone_out(plat):
    c = plat.client()
    login(c)
    r = c.post("/api/auth/change-password", json={"current_password": PW, "new_password": "another long passphrase"}, headers=H)
    assert r.status_code == 200 and r.json()["data"]["sign_in_again"] is True
    assert c.get("/api/auth/me").status_code == 401
    assert login(plat.client(), pw="another long passphrase").status_code == 200
    assert login(plat.client()).status_code == 401


def test_concurrent_requests_in_different_companies_never_cross(plat):
    """40 simultaneous requests alternating between two companies: every record lands in the right database."""
    tok = login(plat.client(), return_token=True).json()["data"]["token"]
    app = create_app(auto_init=False, workspace=plat.ws, plane=plat.plane)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            async def one(i):
                cid = plat.A if i % 2 == 0 else plat.B
                r = await ac.post("/api/resource/Product", json={"title": f"{cid}-{i}"},
                                  headers={"Authorization": f"Bearer {tok}", "X-Velora-Company": cid})
                return cid, r
            return await asyncio.gather(*(one(i) for i in range(40)))

    results = asyncio.run(run())
    assert all(r.status_code == 201 for _, r in results), [r.text for _, r in results if r.status_code != 201][:2]
    for cid in (plat.A, plat.B):
        with plat.plane.company_scope(cid):
            titles = [d["title"] for d in velora.get_list("Product", fields=["title"], limit=100)]
        assert len(titles) == 20 and all(t.startswith(cid + "-") for t in titles)       # nothing from the other company
        names = [r.json()["data"]["name"] for c, r in results if c == cid]
        assert len(set(names)) == 20                                                       # no duplicate numbers within a company


# ============================ CLI ==============================================================
def test_cli_platform_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False); monkeypatch.delenv("VELORA_WORKSPACE", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    run = lambda *a: (main(list(a)), *(lambda o: (o.out, o.err))(capsys.readouterr()))
    code, out, err = run("platform", "init", "--admin-email", "root@example.com", "--admin-password", PW)
    assert code == 0 and "BACK IT UP" in out
    assert run("platform", "init", "--admin-email", "x@y.com", "--admin-password", PW)[0] == 1
    assert run("tenant", "create", "Enterprise Group")[0] == 0
    code, out, _ = run("company", "create", "Velora Technologies", "--tenant", "TEN-001", "--apps", "shop")
    assert code == 0 and "COMP-001" in out and "active" in out
    assert run("company", "create", "Bad", "--tenant", "TEN-999")[0] == 1
    assert run("user", "create", "alice@example.com", "--name", "Alice", "--password", PW)[0] == 0
    assert run("user", "create", "weak@example.com", "--password", "short")[0] == 1
    assert run("user", "grant", "alice@example.com", "COMP-001", "--roles", "System Manager, Sales User")[0] == 0
    assert run("user", "grant", "alice@example.com", "COMP-404", "--roles", "x")[0] == 1
    assert "Product" in run("--company", "COMP-001", "doctypes")[1]
    code, out, _ = run("--company", "COMP-001", "list-apps")
    assert "shop" in out and "installed" in out
    code, out, _ = run("migrate", "--all-companies")
    assert code == 0 and "COMP-001: up to date" in out
    code, out, _ = run("--company", "COMP-001", "backup")
    assert code == 0 and "Backup written" in out and list((ws.root / "platform" / "backups" / "COMP-001").glob("*.db.gz"))
    run("company", "suspend", "COMP-001")
    assert "suspended" in run("company", "list")[1]
    run("company", "activate", "COMP-001")
    assert "companies: 1" in run("platform", "status")[1]
    assert "company.provision" in run("platform", "audit")[1]
    assert "--yes" in run("company", "drop", "COMP-001")[2]
    assert run("company", "drop", "COMP-001", "--yes")[0] == 0
    assert "No companies" in run("company", "list")[1]


# ============================ PostgreSQL ========================================================
pg = pytest.mark.skipif(not PG_ROOT_PW, reason="set VELORA_TEST_PG_ROOT_PASSWORD to test PostgreSQL company databases")


@pg
def test_pg_company_databases_with_encrypted_credentials_and_isolation(tmp_path, monkeypatch):
    from velora import dbadmin
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, db="postgres", root_password=PG_ROOT_PW, admin_email="root@example.com", admin_password=PW)
    cp_cfg = json.loads((ws.root / "platform" / "control_plane.json").read_text())
    try:
        plane.registry.create_tenant("Enterprise Group")
        A = plane.provisioning.provision_company("Enterprise Group", "Company A", apps=["shop"], db="postgres", root_password=PG_ROOT_PW)
        B = plane.provisioning.provision_company("Enterprise Group", "Company B", apps=["shop"], db="postgres", root_password=PG_ROOT_PW)
        assert A["db_name"] != B["db_name"] and A["provisioned_db"] and A["secret_ref"].startswith("local:")
        # no credential anywhere in the registry row; the password is only recoverable with the master key
        pw = plane.secrets.get(A["secret_ref"])
        assert pw and pw not in json.dumps({k: str(v) for k, v in A.items()})
        with plane.engine.connect() as c:
            assert pw not in c.execute(text("select string_agg(ciphertext, ',') from cp_secret")).scalar()
        with plane.company_scope(A["id"]):
            velora.new_doc("Product", title="Customer 001").insert()
        with plane.company_scope(B["id"]):
            assert velora.get_list("Product") == []                                  # a different PostgreSQL database
            assert velora.new_doc("Product", title="Customer 001").insert().name == "P-0001"
        # each company's role can only open its own database
        import sqlalchemy
        other = sqlalchemy.create_engine(f"postgresql+psycopg://{A['db_user']}:{pw}@localhost/{B['db_name']}")
        with pytest.raises(Exception, match="permission denied|password authentication|not allowed"):
            with other.connect() as c:
                c.execute(text("select 1 from tab_product"))
        other.dispose()
        assert plane.backup_company(A).name.endswith(".sql.gz")
        for co in (A, B):
            assert "dropped" in plane.provisioning.drop_company(co["id"], root_password=PG_ROOT_PW)
        root = dbadmin.root_engine("localhost", 5432, "postgres", PG_ROOT_PW)
        with root.connect() as c:
            assert c.execute(text("select count(*) from pg_database where datname like 'velora_company%'")).scalar() == 0
        root.dispose()
    finally:
        plane.dispose()
        dbadmin.drop_pg("localhost", 5432, "postgres", PG_ROOT_PW, cp_cfg["db_name"], cp_cfg["db_user"])


@pg
def test_pg_failed_provisioning_drops_database_role_and_secret(tmp_path, monkeypatch):
    from velora import dbadmin
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws, "bad", "Thing", fail_install=True)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)       # sqlite control plane is fine here
    plane.registry.create_tenant("T")
    with pytest.raises(RuntimeError, match="exploded"):
        plane.provisioning.provision_company("T", "Doomed", apps=["bad"], db="postgres", root_password=PG_ROOT_PW)
    co = plane.registry.list_companies()[0]
    assert co["status"] == "failed"
    root = dbadmin.root_engine("localhost", 5432, "postgres", PG_ROOT_PW)
    with root.connect() as c:
        assert c.execute(text("select count(*) from pg_database where datname=:n"), {"n": co["db_name"]}).scalar() == 0
        assert c.execute(text("select count(*) from pg_roles where rolname=:n"), {"n": co["db_user"]}).scalar() == 0
    root.dispose()
    with plane.engine.connect() as c:
        assert c.execute(select(cpm.secret.c.ref)).first() is None                           # the stored credential was removed too
    plane.dispose()


@pg
def test_pg_concurrent_requests_across_company_pools_never_cross(tmp_path, monkeypatch):
    from velora import dbadmin
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("Group")
    cos = [plane.provisioning.provision_company("Group", f"Company {n}", apps=["shop"], db="postgres", root_password=PG_ROOT_PW) for n in "ABC"]
    try:
        plane.identity.create_user("u@example.com", "U", PW)
        for co in cos:
            plane.identity.grant("u@example.com", co["id"], ["System Manager"])
        tok = plane.identity.authenticate("u@example.com", PW).token
        app = create_app(auto_init=False, workspace=ws, plane=plane)

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
                async def one(i):
                    co = cos[i % 3]
                    r = await ac.post("/api/resource/Product", json={"title": f"{co['id']}-{i}"},
                                      headers={"Authorization": f"Bearer {tok}", "X-Velora-Company": co["id"]})
                    return co["id"], r
                return await asyncio.gather(*(one(i) for i in range(90)))

        results = asyncio.run(run())
        assert all(r.status_code == 201 for _, r in results), [r.text for _, r in results if r.status_code != 201][:2]
        for co in cos:
            with plane.company_scope(co["id"]):
                titles = [d["title"] for d in velora.get_list("Product", fields=["title"], limit=100)]
            assert len(titles) == 30 and all(t.startswith(co["id"] + "-") for t in titles)
            names = [r.json()["data"]["name"] for c, r in results if c == co["id"]]
            assert sorted(names) == [f"P-{n:04d}" for n in range(1, 31)]            # gap-free per company even under concurrency
    finally:
        for co in cos:
            plane.provisioning.drop_company(co["id"], root_password=PG_ROOT_PW)
        plane.dispose()


@pg
def test_two_workspaces_can_share_one_postgresql_server(tmp_path, monkeypatch):
    """Each workspace's control plane gets its own database and role - they must not collide."""
    from velora import dbadmin
    monkeypatch.delenv("VELORA_MASTER_KEY", raising=False)
    made = []
    try:
        for name in ("w1", "w2"):
            ws = Workspace.create(tmp_path / name)
            plane = ControlPlane.create(ws, db="postgres", root_password=PG_ROOT_PW, admin_email="root@example.com", admin_password=PW)
            made.append((plane, plane.cfg["db_name"], plane.cfg["db_user"]))
        assert made[0][1] != made[1][1] and made[0][2] != made[1][2]
    finally:
        for plane, db_name, db_user in made:
            plane.dispose()
            dbadmin.drop_pg("localhost", 5432, "postgres", PG_ROOT_PW, db_name, db_user)


def test_company_duplication_copies_only_selected_doctypes_in_new_database(plat):
    from velora import new_doc, get_list
    with plat.plane.company_scope(plat.A, user_email="Administrator", roles=("System Manager",)):
        source = new_doc("Product", title="Starter Product", price=125).insert()
    c = plat.client()
    r = login(c, "root@example.com")
    assert r.status_code == 200
    r = c.post(f"/api/platform/companies/{plat.A}/duplicate", headers=H,
               json={"name": "Copied Company", "db": "sqlite", "doctypes": ["Product"]})
    assert r.status_code == 200, r.text
    target = r.json()["data"]["company"]
    assert target["id"] != plat.A
    with plat.plane.company_scope(target["id"], user_email="Administrator", roles=("System Manager",)):
        products = get_list("Product", fields=["name", "title", "price"])
        assert len(products) == 1
        assert products[0]["name"] == source.name
        assert products[0]["title"] == "Starter Product"
    c.close()


def test_suspended_tenant_blocks_all_company_requests(plat):
    c = plat.client()
    r = login(c)
    assert r.status_code == 200
    # Alice has access to both companies, but the tenant suspension blocks both.
    plat.plane.registry.set_tenant_status("Enterprise Group", "suspended", actor="root@example.com")
    r = c.get("/api/doctypes", headers=hdr(plat.A))
    assert r.status_code == 423
    c.close()
