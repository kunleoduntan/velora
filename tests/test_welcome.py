"""Welcome page data, the standalone tutorial, the lifecycle event log, and company web addresses (domains)."""
import json
import re
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from velora import eventlog, lifecycle
from velora.api import create_app
from velora.cli import main
from velora.controlplane import ControlPlane
from velora.controlplane.registry import normalize_domain
from velora.exceptions import ValidationError
from velora.workspace import WorkspaceError

from test_lifecycle import lc, run, ext_app, where  # noqa: F401  (the two-company workspace fixture and helpers)

ROOT = Path(__file__).parent.parent
PW = "a long passphrase 1"


# ============================== domain names ==============================
@pytest.mark.parametrize("raw,ok", [("erp.acme.com", "erp.acme.com"), ("ERP.Acme.COM", "erp.acme.com"), ("  acme.ng. ", "acme.ng"), ("a-b.c-d.co.uk", "a-b.c-d.co.uk"), ("xn--bcher-kva.example.org", "xn--bcher-kva.example.org")])
def test_good_domain_names_are_normalised(raw, ok):
    assert normalize_domain(raw) == ok


@pytest.mark.parametrize("raw,frag", [("", "valid domain"), ("localhost", "at least two parts"), ("acme", "at least two parts"), ("https://acme.com", "just the address"), ("acme.com/app", "just the address"),
                                      ("acme.com:8000", "just the address"), ("user@acme.com", "just the address"), ("acme .com", "just the address"), ("-acme.com", "valid domain"), ("acme-.com", "valid domain"),
                                      ("ac_me.com", "valid domain"), ("a..com", "valid domain"), ("192.168.1.5", "IP address"), ("1.2.3.4", "IP address"), ("erp.local", "cannot be reached"),
                                      ("shop.test", "cannot be reached"), ("x" * 64 + ".com", "valid domain"), ("a." * 130 + "com", "valid domain"), ("acme.123", "IP address"), ("ünï.com", "valid domain"), (None, "valid domain")])
def test_bad_domain_names_are_refused_with_a_reason(raw, frag):
    with pytest.raises(ValidationError, match=frag):
        normalize_domain(raw)


# ============================== the registry ==============================
@pytest.fixture
def plane(lc):
    p = ControlPlane.open(lc.ws)
    yield p
    p.dispose()


def test_domains_are_registered_listed_and_removed_with_a_sensible_primary(lc, plane):
    r = plane.registry
    first = r.add_domain("erp.acme.com", lc.a)
    assert first["is_primary"] and first["locked"] and first["status"] == "active" and not first["tls"]                  # the first address is the primary one
    second = r.add_domain("crm.acme.com", lc.a)
    assert not second["is_primary"]
    third = r.add_domain("main.acme.com", lc.a, primary=True)
    assert third["is_primary"] and not r.get_domain("erp.acme.com")["is_primary"]                                         # asking for primary moves it
    assert [d["domain"] for d in r.list_domains(lc.a)] == ["crm.acme.com", "erp.acme.com", "main.acme.com"] and r.list_domains(lc.b) == []
    assert r.remove_domain("main.acme.com") is True and sum(d["is_primary"] for d in r.list_domains(lc.a)) == 1           # another becomes primary
    assert r.remove_domain("nope.acme.com") is False
    r.set_domain_tls("erp.acme.com", True)
    assert r.get_domain("erp.acme.com")["tls"] is True


def test_an_address_belongs_to_exactly_one_company_and_unknown_companies_are_refused(lc, plane):
    r = plane.registry
    r.add_domain("erp.acme.com", lc.a)
    with pytest.raises(ValidationError, match=f"already registered for {lc.a}"):
        r.add_domain("erp.acme.com", lc.b)
    with pytest.raises(ValidationError, match="already registered"):
        r.add_domain("ERP.ACME.COM", lc.a)                                                                              # case does not make it a different address
    with pytest.raises(ValidationError, match="No such company"):
        r.add_domain("x.acme.com", "COMP-999")
    with pytest.raises(ValidationError, match="valid domain"):
        r.add_domain("nodots", lc.a)


def test_the_company_an_address_opens_is_found_from_the_host_header(lc, plane):
    r = plane.registry
    r.add_domain("erp.acme.com", lc.a, locked=False)
    for host in ("erp.acme.com", "ERP.Acme.com", "erp.acme.com:8443", "erp.acme.com."):
        got = r.company_for_domain(host)
        assert got["id"] == lc.a and got["domain"] == "erp.acme.com" and got["locked"] is False
    assert r.company_for_domain("other.acme.com") is None and r.company_for_domain("") is None and r.company_for_domain(None) is None


# ============================== the address decides the company ==============================
@pytest.fixture
def api(lc, plane):
    plane.identity.create_user("both@acme.ng", "Both Co", PW)
    plane.identity.grant("both@acme.ng", lc.a, ["System Manager"])
    plane.identity.grant("both@acme.ng", lc.b, ["System Manager"])
    app = create_app(auto_init=False, workspace=lc.ws, plane=plane)
    return TestClient(app)


def login(api, host=None):
    h = {"host": host} if host else {}
    r = api.post("/api/auth/login", json={"email": "both@acme.ng", "password": PW, "return_token": True}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_the_public_domain_endpoint_names_the_company_for_the_address(lc, plane, api):
    plane.registry.add_domain("erp.acme.com", lc.a)
    d = api.get("/api/domain", headers={"host": "erp.acme.com"}).json()["data"]
    assert d["domain"] == "erp.acme.com" and d["company"]["id"] == lc.a and d["locked"] is True
    assert api.get("/api/domain", headers={"host": "unknown.acme.com"}).json()["data"] == {"domain": None, "company": None, "locked": False}


def test_on_a_locked_address_you_see_and_reach_only_that_company(lc, plane, api):
    plane.registry.add_domain("erp.acme.com", lc.a)
    data = login(api, "erp.acme.com")
    assert [c["id"] for c in data["companies"]] == [lc.a] and data["active_company"] == lc.a                           # only company A is offered, and it is already active
    tok = {"Authorization": f"Bearer {data['token']}", "host": "erp.acme.com"}
    assert api.get("/api/welcome", headers=tok).json()["data"]["company"]["id"] == lc.a                                  # no company header needed: the address decides
    r = api.get("/api/welcome", headers={**tok, "X-Velora-Company": lc.b})
    assert r.status_code == 403 and "for" in r.json()["message"] and "only" in r.json()["message"]                       # asking for B on A's address is refused
    assert api.get("/api/welcome", headers={**tok, "X-Velora-Company": lc.a}).status_code == 200


def test_the_same_person_can_still_reach_every_company_from_an_unbound_address(lc, plane, api):
    plane.registry.add_domain("erp.acme.com", lc.a)
    data = login(api, "console.example.org")
    assert sorted(c["id"] for c in data["companies"]) == sorted([lc.a, lc.b])
    tok = {"Authorization": f"Bearer {data['token']}", "host": "console.example.org"}
    assert api.get("/api/welcome", headers={**tok, "X-Velora-Company": lc.b}).json()["data"]["company"]["id"] == lc.b


def test_an_unlocked_address_defaults_to_its_company_but_allows_switching(lc, plane, api):
    plane.registry.add_domain("shared.acme.com", lc.a, locked=False)
    data = login(api, "shared.acme.com")
    assert sorted(c["id"] for c in data["companies"]) == sorted([lc.a, lc.b]) and data["active_company"] == lc.a
    tok = {"Authorization": f"Bearer {data['token']}", "host": "shared.acme.com"}
    assert api.get("/api/welcome", headers=tok).json()["data"]["company"]["id"] == lc.a
    assert api.get("/api/welcome", headers={**tok, "X-Velora-Company": lc.b}).json()["data"]["company"]["id"] == lc.b


def test_a_removed_address_stops_binding(lc, plane, api):
    plane.registry.add_domain("erp.acme.com", lc.a)
    plane.registry.remove_domain("erp.acme.com")
    assert sorted(c["id"] for c in login(api, "erp.acme.com")["companies"]) == sorted([lc.a, lc.b])


# ============================== `velora domain` ==============================
def helper_script(tmp_path, code=0, out="ok"):
    f = tmp_path / "helper.sh"
    f.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/helper.log\necho "{out}"\nexit {code}\n')
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f


def configure(lc, helper=None, **extra):
    cfg = {"port": 8001, "email": "ops@acme.ng", **extra}
    if helper:
        cfg["helper"] = str(helper)
    lc.ws.update_config(domain=cfg)


def test_adding_a_domain_registers_configures_the_web_server_and_https_in_one_step(lc, tmp_path, monkeypatch):
    from velora import domains
    configure(lc, helper_script(tmp_path))
    monkeypatch.setattr(domains, "resolve", lambda d: ["203.0.113.9"])
    res = domains.add(lc.ws, "ERP.Acme.com", lc.a, log=lambda m: None)
    assert res == {"domain": "erp.acme.com", "company": lc.a, "tls": True, "helper": True}
    assert (tmp_path / "helper.log").read_text().strip() == "add erp.acme.com --port 8001 --email ops@acme.ng"                # exactly what the root helper is told
    p = ControlPlane.open(lc.ws)
    try:
        d = p.registry.get_domain("erp.acme.com")
    finally:
        p.dispose()
    assert d["company_id"] == lc.a and d["tls"] is True and d["locked"] is True
    ev = eventlog.recent(lc.ws)[0]
    assert ev["kind"] == "domain" and ev["ok"] and ev["domain"] == "erp.acme.com" and any("HTTPS certificate" in s["text"] for s in ev["steps"])


def test_without_dns_https_is_refused_up_front_and_nothing_is_registered(lc, tmp_path, monkeypatch, capsys):
    from velora import domains
    configure(lc, helper_script(tmp_path))
    monkeypatch.setattr(domains, "resolve", lambda d: [])
    with pytest.raises(WorkspaceError, match="does not exist in DNS yet.*A record.*Nothing was changed"):
        domains.add(lc.ws, "erp.acme.com", lc.a, log=lambda m: None)
    assert not (tmp_path / "helper.log").exists() and domains.listing(lc.ws) == []
    res = domains.add(lc.ws, "erp.acme.com", lc.a, tls=False, log=lambda m: None)                                       # --no-tls: fine to register before DNS exists
    assert res["tls"] is False and "--no-tls" in (tmp_path / "helper.log").read_text()


def test_if_the_web_server_step_fails_the_registration_is_undone(lc, tmp_path, monkeypatch):
    from velora import domains
    configure(lc, helper_script(tmp_path, code=3, out="could not get a certificate"))
    monkeypatch.setattr(domains, "resolve", lambda d: ["203.0.113.9"])
    with pytest.raises(WorkspaceError, match="Could not add erp.acme.com.*could not get a certificate"):
        domains.add(lc.ws, "erp.acme.com", lc.a, log=lambda m: None)
    assert domains.listing(lc.ws) == []                                                                                   # all or nothing
    ev = eventlog.recent(lc.ws)[0]
    assert ev["kind"] == "domain" and ev["ok"] is False and "Web-server setup failed" in ev["steps"][0]["text"]


def test_a_server_without_the_helper_still_registers_and_prints_the_nginx_site(lc, monkeypatch):
    from velora import domains
    configure(lc)
    monkeypatch.setattr(domains, "resolve", lambda d: [])
    out = []
    res = domains.add(lc.ws, "erp.acme.com", lc.a, log=out.append)
    assert res["helper"] is False and res["tls"] is False
    text = "\n".join(out)
    assert "server_name erp.acme.com;" in text and "proxy_pass http://127.0.0.1:8001;" in text and "proxy_buffering off" in text and "proxy_set_header Host $host" in text


def test_domain_add_remove_list_check_through_the_command_line(lc, tmp_path, monkeypatch, capsys):
    from velora import domains
    configure(lc, helper_script(tmp_path))
    monkeypatch.setattr(domains, "resolve", lambda d: ["203.0.113.9"])
    assert run(capsys, "domain", "list")[1].startswith("No domains yet")
    code, out, err = run(capsys, "domain", "add", "erp.acme.com", lc.a)
    assert code == 0 and "erp.acme.com -> " in out and "Done: https://erp.acme.com" in out, err
    code, out, _ = run(capsys, "domain", "list")
    assert "erp.acme.com" in out and lc.a in out and "primary" in out and "https" in out and "locked" in out
    assert "points to 203.0.113.9" in run(capsys, "domain", "check", "erp.acme.com")[1]
    monkeypatch.setattr(domains, "resolve", lambda d: [])
    assert "does not resolve in DNS yet" in run(capsys, "domain", "check", "erp.acme.com")[1]
    code, out, _ = run(capsys, "domain", "remove", "erp.acme.com")
    assert code == 0 and "Removed erp.acme.com" in out and "remove erp.acme.com" in (tmp_path / "helper.log").read_text() and domains.listing(lc.ws) == []
    code, _, err = run(capsys, "domain", "remove", "erp.acme.com")
    assert code == 1 and "is not registered" in err


@pytest.mark.parametrize("args,frag", [(["add"], "Give the address"), (["add", "nodots", "COMP-001"], "at least two parts"), (["add", "erp.acme.com", "COMP-999"], "No such company"),
                                       (["add", "erp.acme.com"], "Which company is this address for"), (["check"], "Give the address")])
def test_the_domain_command_explains_mistakes(lc, capsys, args, frag):
    code, _, err = run(capsys, "domain", *args)
    assert code == 1 and frag in err


def test_a_dry_run_changes_nothing_and_a_duplicate_is_refused(lc, tmp_path, monkeypatch, capsys):
    from velora import domains
    configure(lc, helper_script(tmp_path))
    monkeypatch.setattr(domains, "resolve", lambda d: ["203.0.113.9"])
    code, out, _ = run(capsys, "domain", "add", "erp.acme.com", lc.a, "--dry-run")
    assert code == 0 and "Dry run: nothing was changed." in out and domains.listing(lc.ws) == [] and not (tmp_path / "helper.log").exists()
    assert run(capsys, "domain", "add", "erp.acme.com", lc.a)[0] == 0
    code, _, err = run(capsys, "domain", "add", "erp.acme.com", lc.b)
    assert code == 1 and f"already registered for {lc.a}" in err and "Remove it first" in err


def test_a_workspace_with_one_company_needs_no_company_argument(tmp_path, monkeypatch):
    # (the lc fixture has two companies; build a one-company workspace)
    from velora import domains
    from velora.workspace import Workspace
    from upgrade_helpers import make_app, clean_modules
    before_path, before_mods = list(sys.path), set(sys.modules)
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE", "VELORA_DB_URL"):
        monkeypatch.delenv(k, raising=False)
    ws = Workspace.create(tmp_path / "one")
    monkeypatch.chdir(ws.root)
    make_app(ws)
    p = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    p.registry.create_tenant("G")
    cid = p.provisioning.provision_company("G", "Only", apps=[])["id"]
    p.dispose()
    monkeypatch.setattr(domains, "resolve", lambda d: [])
    assert domains.add(ws, "only.example.org", None, tls=False, log=lambda m: None)["company"] == cid
    clean_modules(tmp_path, before_path, before_mods)


# ============================== the lifecycle event log ==============================
def test_the_log_keeps_the_newest_events_and_survives_a_damaged_file(lc):
    for i in range(55):
        eventlog.record(lc.ws, "update", f"Event {i}", [f"step {i}", {"text": "bad one", "ok": False}], ok=i % 2 == 0, extra=None, app="x")
    ev = eventlog.recent(lc.ws, 100)
    assert len(ev) == eventlog.MAX_EVENTS and ev[0]["title"] == "Event 54" and ev[-1]["title"] == "Event 5"             # newest first, oldest dropped
    assert ev[0]["steps"] == [{"text": "step 54", "ok": True}, {"text": "bad one", "ok": False}] and ev[0]["app"] == "x" and "extra" not in ev[0] and ev[0]["id"] and ev[0]["at"].endswith("+00:00")
    assert len(eventlog.recent(lc.ws, 3)) == 3
    lc.ws.events_file.write_text("{ not json")
    assert eventlog.recent(lc.ws) == []
    assert eventlog.record(lc.ws, "install", "Fresh start")["title"] == "Fresh start" and [e["title"] for e in eventlog.recent(lc.ws)] == ["Fresh start"]
    assert eventlog.recent(None) == []                                                                                    # no workspace (library mode): nothing to show


def test_an_update_report_is_explained_in_plain_words():
    rep = {"status": "success", "code": {"framework": {"from": "0.8.1", "to": "0.9.0"}, "apps": [{"name": "inventory", "from": "1", "to": "2", "commits": 3}]}, "packages": ["numpy>=1.26"],
           "upgrade": {"snapshot": "/srv/b/upgrade-1", "targets": [{"label": "COMP-001 Acme", "status": "upgraded"}, {"label": "COMP-002 Beta", "status": "upgraded"}]},
           "features": [{"app": "velora_search", "target": "COMP-001", "status": "installed"}], "restart": {"ok": True}}
    title, ok, steps, details = eventlog.from_update_report(rep)
    texts = [s["text"] for s in steps]
    assert title == "Update complete" and ok and details == {"from_version": "0.8.1", "to_version": "0.9.0"}
    assert texts[0] == "Updated Velora from 0.8.1 to 0.9.0" and "Updated the app inventory (3 change(s))" in texts and any(t.startswith("Installed or updated Python packages: numpy") for t in texts)
    assert any("Backed up every database first" in t for t in texts) and "Upgraded 2 database(s): COMP-001 Acme, COMP-002 Beta" in texts and "Turned on velora_search for COMP-001" in texts and texts[-1] == "Restarted the server"
    bad = {"status": "rolled_back", "upgrade": {"targets": [{"label": "COMP-002 Beta", "status": "failed", "error": "column x is missing"}]}, "restart": {"ok": False, "output": "boom"}}
    title, ok, steps, _ = eventlog.from_update_report(bad)
    assert title == "Update failed and was undone" and not ok and any(s["ok"] is False and "COMP-002 Beta could not be upgraded: column x is missing" in s["text"] for s in steps)
    assert any("put back exactly as they were" in s["text"] for s in steps) and any("Restart failed: boom" in s["text"] for s in steps)
    assert eventlog.from_update_report({"status": "up_to_date", "upgrade": {"targets": [{"label": "A", "status": "up_to_date"}]}})[2][0]["text"] == "Checked 1 database(s): already current"


def test_every_lifecycle_command_leaves_a_record(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    run(capsys, "install-app", "velora_search", "--no-restart")
    ev = eventlog.recent(lc.ws)[0]
    assert ev["kind"] == "install-app" and ev["app"] == "velora_search" and ev["ok"] and len(ev["steps"]) == 2 and "installed" in ev["steps"][0]["text"]
    run(capsys, "install-app", "velora_search", "--no-restart")                                                          # nothing changed: nothing recorded
    assert len(eventlog.recent(lc.ws)) == 1
    lc.ws.update_config(default_apps=["velora_notify"])
    run(capsys, "update")
    ev = eventlog.recent(lc.ws)[0]
    assert ev["kind"] == "update" and ev["ok"] and any("Turned on velora_notify" in s["text"] for s in ev["steps"])
    n = len(eventlog.recent(lc.ws))
    run(capsys, "update")
    assert len(eventlog.recent(lc.ws)) == n                                                                              # an update that found nothing is not worth an entry
    run(capsys, "uninstall-app", "velora_search", "--yes", "--no-restart")
    ev = eventlog.recent(lc.ws)[0]
    assert ev["kind"] == "uninstall-app" and ev["app"] == "velora_search" and any("a backup was taken first" in s["text"] for s in ev["steps"])


def test_the_quickstart_records_what_it_set_up(tmp_path, monkeypatch):
    from velora.quickstart import quickstart
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE", "VELORA_DB_URL"):
        monkeypatch.delenv(k, raising=False)
    before_path, before_mods = list(sys.path), set(sys.modules)
    res = quickstart(str(tmp_path / "qs"), email="boss@acme.ng", password=PW, company="Acme Ltd", sample=False)
    from velora.workspace import Workspace
    ev = eventlog.recent(Workspace(tmp_path / "qs"))[0]
    assert ev["kind"] == "install" and ev["title"] == "Velora is installed and ready" and ev["company"] == res["company"]
    t = " | ".join(s["text"] for s in ev["steps"])
    assert "Created your workspace" in t and "control plane" in t and "Acme Ltd" in t and "velora_notify" in t and "boss@acme.ng" in t
    from upgrade_helpers import clean_modules
    clean_modules(tmp_path, before_path, before_mods)


# ============================== the welcome API and the tutorial ==============================
def test_the_welcome_data_describes_this_company_and_what_just_happened(lc, plane, api):
    lifecycle.install_everywhere(lc.ws, "velora_notify", do_restart=False, log=lambda m: None)
    plane.registry.add_domain("erp.acme.com", lc.a)
    plane.registry.set_domain_tls("erp.acme.com", True)
    tok = {"Authorization": f"Bearer {login(api)['token']}", "X-Velora-Company": lc.a}
    r = api.get("/api/welcome", headers=tok)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["product"] == "Velora" and d["powered_by"] == "Velora BiZ Solutions" and d["tutorial_url"] == "/tutorial" and d["platform"] is True
    assert d["company"] == {"id": lc.a, "name": "A"} and d["is_admin"] is True and d["user"] == "both@acme.ng"
    assert d["latest"]["kind"] == "install-app" and d["latest"]["app"] == "velora_notify" and d["events"][0] == d["latest"]
    assert d["features"] == {"notifications": True, "search": False, "accounts": False}
    names = {a["name"]: a for a in d["apps"]}
    assert names["velora_notify"]["built_in"] is True and names["velora_notify"]["title"] == "Notifications"
    assert d["domains"] == [{"domain": "erp.acme.com", "primary": True, "tls": True, "locked": True}]
    assert api.get("/api/welcome").status_code in (401, 403)                                                            # it describes a company: sign in first


def test_a_person_who_is_not_an_administrator_is_told_so(lc, plane, api):
    plane.identity.create_user("clerk@acme.ng", "Clerk", PW)
    plane.identity.grant("clerk@acme.ng", lc.a, ["Accounts User"])
    tok = api.post("/api/auth/login", json={"email": "clerk@acme.ng", "password": PW, "return_token": True}).json()["data"]["token"]
    d = api.get("/api/welcome", headers={"Authorization": f"Bearer {tok}", "X-Velora-Company": lc.a}).json()["data"]
    assert d["is_admin"] is False and d["company"]["id"] == lc.a


def test_the_tutorial_opens_without_signing_in(lc, plane, api):
    r = api.get("/tutorial")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and r.headers["cache-control"] == "no-cache" and r.headers["x-content-type-options"] == "nosniff"
    assert "Powered by <b>Velora BiZ Solutions</b>" in r.text and "<title>Velora Tutorial" in r.text
    assert api.get("/tutorial/").status_code == 200


def test_a_missing_tutorial_file_is_a_clear_404(lc, plane, api, monkeypatch, tmp_path):
    from velora.api import welcome
    monkeypatch.setattr(welcome, "TUTORIAL", tmp_path / "nope.html")
    r = api.get("/tutorial")
    assert r.status_code == 404 and "missing" in r.json()["message"]


def test_the_welcome_endpoint_also_works_without_a_workspace(tmp_path):
    import velora
    from velora.permissions import Session
    velora.init(velora.configure(db_url=f"sqlite:///{tmp_path / 'lib.db'}", apps=["velora_notify"], developer_mode=True))
    velora.migrate()
    try:
        d = TestClient(create_app(auto_init=False)).get("/api/welcome", headers={"X-Velora-User": "boss", "X-Velora-Roles": "System Manager"}).json()["data"]
        assert d["events"] == [] and d["latest"] is None and d["company"] is None and d["domains"] == [] and d["platform"] is False and d["features"]["notifications"] is True
    finally:
        velora.shutdown()


# ============================== the tutorial stays true ==============================
TUTORIAL = (ROOT / "velora" / "static" / "tutorial.html").read_text()


def test_the_tutorial_is_one_self_contained_page():
    assert not re.findall(r'(?:src|href)="(?:https?:)?//', TUTORIAL) and "@import" not in TUTORIAL and "<link " not in TUTORIAL     # no fonts, no CDN: works offline
    assert TUTORIAL.count("<script") == 1 and "Powered by <b>Velora BiZ Solutions</b>" in TUTORIAL and 'name="viewport"' in TUTORIAL and "@media print" in TUTORIAL


def test_every_link_inside_the_tutorial_goes_somewhere():
    page = re.sub(r"<script>.*?</script>", "", TUTORIAL, flags=re.S)                                                       # (the script builds links at run time; check the page itself)
    ids = set(re.findall(r'id="([^"]+)"', page))
    anchors = set(re.findall(r'href="#([^"]*)"', page))
    assert not [a for a in anchors if a and a not in ids], [a for a in anchors if a and a not in ids]
    sections = re.findall(r'<section id="([^"]+)"', TUTORIAL)
    assert len(sections) == len(set(sections)) >= 25 and all(f'<span class="n">{i}</span>' in TUTORIAL for i in range(1, len(sections) + 1))


def test_every_velora_command_the_tutorial_shows_really_exists():
    """The tutorial must never describe a command that is not there."""
    from velora.cli import _build_parser
    sub = next(a for a in _build_parser()._actions if a.__class__.__name__ == "_SubParsersAction")
    real = set(sub.choices)
    text = re.sub(r"<[^>]+>", " ", TUTORIAL)
    mentioned = set(re.findall(r"(?:^|[\s`(;&|])(?:sudo )?velora ([a-z][a-z-]+)\b", text, re.M))
    mentioned -= {"is", "the", "a", "does", "can", "keeps", "gives", "also", "then", "in", "to", "and", "or", "as", "itself", "never", "app", "apps", "framework", "ideas", "fix", "writes", "check", "looks", "owns", "starts", "needs", "import"}      # ("from velora import Document" is Python, not a command)
    unknown = sorted(m for m in mentioned if m not in real)
    assert not unknown, f"the tutorial mentions commands that do not exist: {unknown} (real: {sorted(real)})"
    assert {"quickstart", "install-app", "uninstall-app", "update", "domain", "doctor", "new-app", "new-doctype", "deps", "pg", "backup", "restore"} <= mentioned | real
    for code in re.findall(r"velora domain (add|list|remove|check)\b", TUTORIAL):
        assert code in ("add", "list", "remove", "check")


def test_the_tutorial_ships_in_the_wheel_definition():
    try:
        import tomllib
    except ModuleNotFoundError:          # Python 3.10
        import tomli as tomllib
    pkg = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["setuptools"]["package-data"]["velora"]
    assert "static/*.html" in pkg
