"""One command each: install-app, uninstall-app, update, and a server that runs its own worker and upgrades itself."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from velora import lifecycle, new_doc
from velora.cli import main
from velora.controlplane import ControlPlane
from velora.scaffold import new_app, new_doctype
from velora.settings import get_setting, set_setting
from velora.workspace import Workspace, WorkspaceError
from upgrade_helpers import PW, clean_modules, make_app


PGROOT = os.environ.get("VELORA_TEST_PG_ROOT_PASSWORD")


@pytest.fixture(params=["sqlite"] + (["postgres"] if PGROOT else []))
def lc(request, tmp_path, monkeypatch):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE", "VELORA_DB_URL"):
        monkeypatch.delenv(k, raising=False)
    before_path, before_mods = list(sys.path), set(sys.modules)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    make_app(ws)                                                                                                      # 'shop' lives in the workspace
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("G")
    kw = {"db": "postgres", "root_password": PGROOT} if request.param == "postgres" else {}
    a = plane.provisioning.provision_company("G", "A", apps=[], **kw)["id"]
    b = plane.provisioning.provision_company("G", "B", apps=[], **kw)["id"]
    marker = tmp_path / "restarts.txt"
    ws.update_config(update={"restart_command": f"echo restarted >> {marker}"})
    plane.dispose()
    yield SimpleNamespace(ws=ws, a=a, b=b, marker=marker, tmp=tmp_path)
    if request.param == "postgres":                                                                                   # leave no databases or roles behind
        p2 = ControlPlane.open(ws)
        for cid in (a, b):
            try:
                p2.provisioning.drop_company(cid, root_password=PGROOT)
            except Exception:  # noqa: BLE001
                pass
        p2.dispose()
    clean_modules(tmp_path, before_path, before_mods)


def ext_app(tmp, name, doctype, requires=(), hooks=""):
    """An app OUTSIDE the workspace (what you would fetch from git or copy from a folder)."""
    src = tmp / "src"
    src.mkdir(exist_ok=True)
    root = new_app(src, name, module=name.title())
    new_doctype(root, name, doctype, module=name.title())
    h = root / name / "hooks.py"
    h.write_text(h.read_text() + (f"\nrequired_apps = {list(requires)!r}\n" if requires else "") + hooks)
    return root


def where(lc, app):
    """{company: installed?}"""
    return {t.id: app in lifecycle.installed_in(lc.ws, t) for t in lifecycle.targets(lc.ws)}


def restarts(lc):
    return lc.marker.read_text().count("restarted") if lc.marker.exists() else 0


def run(capsys, *argv):
    code = main(list(argv))
    o = capsys.readouterr()
    return code, o.out, o.err


# ============================== install-app: one command, every company ==============================
def test_installing_an_app_from_a_folder_does_everything_in_one_command(lc, capsys):
    src = ext_app(lc.tmp, "widgetapp", "Widget")
    code, out, err = run(capsys, "install-app", str(src))
    assert code == 0, err
    assert (lc.ws.apps_dir / "widgetapp" / "widgetapp" / "__init__.py").exists()                                       # fetched into the workspace
    assert where(lc, "widgetapp") == {lc.a: True, lc.b: True}                                                          # installed on EVERY company
    assert "installed on 2 of 2 company(ies)" in out and restarts(lc) == 1                                              # and the server was restarted, once


def test_running_it_again_is_harmless_and_does_not_restart(lc, capsys):
    src = ext_app(lc.tmp, "widgetapp", "Widget")
    run(capsys, "install-app", str(src))
    code, out, _ = run(capsys, "install-app", "widgetapp")
    assert code == 0 and "already installed" in out and "installed on 0 of 2" in out and restarts(lc) == 1            # nothing changed, nothing restarted


def test_an_app_can_be_fetched_from_a_git_url(lc, capsys):
    src = ext_app(lc.tmp, "gitapp", "GitThing")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(cmd, cwd=src, check=True, capture_output=True)
    code, out, err = run(capsys, "install-app", f"file://{src}")
    assert code == 0, err
    assert "Fetching file://" in out and where(lc, "gitapp") == {lc.a: True, lc.b: True}


def test_built_in_apps_install_by_name(lc, capsys):
    code, out, _ = run(capsys, "install-app", "velora_search")
    assert code == 0 and where(lc, "velora_search") == {lc.a: True, lc.b: True}


def test_one_company_can_be_chosen_with_the_global_flag(lc, capsys):
    code, out, _ = run(capsys, "--company", lc.a, "install-app", "velora_notify")
    assert code == 0 and where(lc, "velora_notify") == {lc.a: True, lc.b: False}
    assert run(capsys, "install-app", "velora_notify")[0] == 0 and where(lc, "velora_notify") == {lc.a: True, lc.b: True}            # then the rest


def test_an_unknown_source_says_what_is_available(lc, capsys):
    code, _, err = run(capsys, "install-app", "no_such_app")
    assert code == 1 and "'no_such_app' is not an app in this workspace" in err and "shop" in err and "velora_notify" in err
    code, _, err = run(capsys, "install-app", str(lc.tmp / "missing_dir"))
    assert code == 1 and "is not an app in this workspace" in err
    (lc.tmp / "plain").mkdir()
    code, _, err = run(capsys, "install-app", str(lc.tmp / "plain"))
    assert code == 1 and "is not a Velora app" in err and not (lc.ws.apps_dir / "plain").exists()                       # a bad folder leaves nothing behind


def test_apps_an_app_needs_are_installed_first_by_themselves(lc, capsys):
    base = ext_app(lc.tmp, "baseapp", "BaseThing")
    top = ext_app(lc.tmp, "topapp", "TopThing", requires=["baseapp"])
    assert run(capsys, "install-app", str(base), "--no-restart")[0] == 0                                               # baseapp is now in the workspace ...
    assert run(capsys, "uninstall-app", "baseapp", "--yes", "--no-restart")[0] == 0                                    # ... but installed nowhere
    code, out, err = run(capsys, "install-app", str(top), "--no-restart")
    assert code == 0, out + err
    assert where(lc, "baseapp") == {lc.a: True, lc.b: True} and where(lc, "topapp") == {lc.a: True, lc.b: True}        # one command installed both, the needed one first
    assert "(baseapp, topapp)" in out


def test_a_missing_required_app_is_reported_before_anything_changes(lc, capsys):
    top = ext_app(lc.tmp, "orphanapp", "OrphanThing", requires=["ghostapp"])
    code, _, err = run(capsys, "install-app", str(top))
    assert code == 1 and "needs the app ghostapp, which is not available here" in err
    assert where(lc, "orphanapp") == {lc.a: False, lc.b: False}


def test_a_problem_in_one_company_does_not_stop_the_others(lc, capsys):
    hook = '\ndef _boom():\n    import velora\n    if velora.current_company().id == "%s":\n        raise RuntimeError("this company cannot take it")\nafter_install = "flakyapp.hooks._boom"\n' % lc.b
    src = ext_app(lc.tmp, "flakyapp", "Flaky", hooks=hook)
    code, out, _ = run(capsys, "install-app", str(src), "--no-restart")
    assert code == 1 and "installed on 1 of 2" in out and "1 FAILED" in out and f"{lc.b}" in out
    assert where(lc, "flakyapp") == {lc.a: True, lc.b: False}                                                           # A has it; B was rolled back, not half-installed


def test_a_restart_that_fails_is_reported_but_the_install_stands(lc, capsys):
    lc.ws.update_config(update={"restart_command": "exit 3"})
    code, out, _ = run(capsys, "install-app", "velora_search")
    assert code == 0 and "Restart failed" in out and where(lc, "velora_search") == {lc.a: True, lc.b: True}
    lc.ws.update_config(update=None)
    code, out, _ = run(capsys, "install-app", "velora_notify")
    assert code == 0 and "No restart command is configured" in out


def test_no_restart_skips_it(lc, capsys):
    run(capsys, "install-app", "velora_search", "--no-restart")
    assert restarts(lc) == 0


# ============================== uninstall-app ==============================
def installed_widget(lc, capsys):
    src = ext_app(lc.tmp, "widgetapp", "Widget")
    run(capsys, "install-app", str(src), "--no-restart")
    t = next(t for t in lifecycle.targets(lc.ws) if t.id == lc.a)
    with lifecycle.in_target(t):
        from velora.meta.registry import registry
        field = next(f.fieldname for f in registry.get("Widget").fields if f.fieldtype == "Data")
        new_doc("Widget", **{field: "precious data"}).insert()
    return t


def rows(lc, t):
    with lifecycle.in_target(t):
        from velora import db
        with db.transaction() as c:
            return c.exec_driver_sql("select count(*) from tab_widget").scalar()


def test_uninstall_backs_up_first_removes_it_everywhere_and_keeps_the_data(lc, capsys):
    t = installed_widget(lc, capsys)
    code, out, err = run(capsys, "uninstall-app", "widgetapp", "--yes")
    assert code == 0, err
    assert where(lc, "widgetapp") == {lc.a: False, lc.b: False} and restarts(lc) == 1
    backups = sorted((lc.ws.root / "backups" / "pre-uninstall").iterdir())
    assert len(backups) == 2 and all(b.stat().st_size > 0 for b in backups) and "[backup: " in out                     # one backup per company, before anything changed
    run(capsys, "install-app", "widgetapp", "--no-restart")
    assert rows(lc, t) == 1                                                                                              # reinstalling brings the data straight back


def test_purge_deletes_the_data_but_only_after_a_backup(lc, capsys):
    t = installed_widget(lc, capsys)
    code, _, err = run(capsys, "uninstall-app", "widgetapp", "--yes", "--purge", "--no-backup")
    assert code == 1 and "always takes a backup first" in err and where(lc, "widgetapp")[lc.a] is True
    code, out, _ = run(capsys, "uninstall-app", "widgetapp", "--yes", "--purge", "--no-restart")
    assert code == 0 and "data deleted" in out
    with lifecycle.in_target(t):
        from sqlalchemy import inspect
        from velora import db
        with db.transaction() as c:
            assert not inspect(c).has_table("tab_widget")
    assert any(p.stat().st_size > 0 for p in (lc.ws.root / "backups" / "pre-uninstall").iterdir())


def test_nothing_is_removed_anywhere_if_another_app_needs_it(lc, capsys):
    base = ext_app(lc.tmp, "baseapp", "BaseThing")
    top = ext_app(lc.tmp, "topapp", "TopThing", requires=["baseapp"])
    run(capsys, "install-app", str(base), "--no-restart")
    run(capsys, "install-app", str(top), "--no-restart")
    assert where(lc, "baseapp") == {lc.a: True, lc.b: True}
    code, _, err = run(capsys, "uninstall-app", "baseapp", "--yes")
    assert code == 1 and "topapp" in err and "Nothing was changed" in err
    assert where(lc, "baseapp") == {lc.a: True, lc.b: True} and not (lc.ws.root / "backups" / "pre-uninstall").exists()


def test_removing_the_code_is_refused_while_another_company_still_uses_it(lc, capsys):
    run(capsys, "install-app", str(ext_app(lc.tmp, "widgetapp", "Widget")), "--no-restart")
    code, _, err = run(capsys, "--company", lc.a, "uninstall-app", "widgetapp", "--yes", "--remove-code")
    assert code == 1 and "still installed on" in err and (lc.ws.apps_dir / "widgetapp").exists() and where(lc, "widgetapp")[lc.a] is True
    code, out, _ = run(capsys, "uninstall-app", "widgetapp", "--yes", "--remove-code", "--no-restart")
    assert code == 0 and "Removed apps/widgetapp" in out and not (lc.ws.apps_dir / "widgetapp").exists()
    assert run(capsys, "uninstall-app", "velora_search", "--yes", "--remove-code")[0] == 1                               # built-in code can never be removed


def test_uninstall_asks_first_when_you_are_at_a_terminal_and_refuses_when_not(lc, capsys, monkeypatch):
    run(capsys, "install-app", "velora_search", "--no-restart")
    code, _, err = run(capsys, "uninstall-app", "velora_search")                                                        # no --yes and no terminal
    assert code == 1 and "Re-run with --yes" in err and where(lc, "velora_search")[lc.a] is True
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert run(capsys, "uninstall-app", "velora_search")[1].strip().endswith("Cancelled.") and where(lc, "velora_search")[lc.a] is True
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert run(capsys, "uninstall-app", "velora_search", "--no-restart")[0] == 0 and where(lc, "velora_search") == {lc.a: False, lc.b: False}


def test_uninstalling_something_that_is_not_installed_is_calm(lc, capsys):
    code, out, _ = run(capsys, "uninstall-app", "shop", "--yes")
    assert code == 0 and "is not installed on any companies" in out and restarts(lc) == 0
    assert run(capsys, "uninstall-app", "nope", "--yes")[0] == 1


# ============================== keeping current ==============================
def test_update_remembers_where_updates_come_from_and_is_calm_when_there_is_nothing_to_do(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    code, out, err = run(capsys, "update", "--framework-source", "https://example.com/simple/velora", "--yes")
    assert code == 0, err
    assert lc.ws.common_config()["update"]["framework_source"] == "https://example.com/simple/velora"
    assert lc.ws.common_config()["update"]["restart_command"].startswith("echo restarted")                                # existing settings are kept
    assert "Everything is already up to date." in out


def test_update_turns_on_built_in_features_that_are_configured_but_missing(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    lc.ws.update_config(default_apps=["velora_notify", "velora_search"])
    code, out, _ = run(capsys, "update")
    assert code == 0 and "Enabled velora_notify on" in out and "Enabled velora_search on" in out
    assert where(lc, "velora_notify") == {lc.a: True, lc.b: True}
    code, out, _ = run(capsys, "update")
    assert code == 0 and "Enabled" not in out and "Everything is already up to date." in out                           # and never twice


def test_new_companies_get_the_default_apps_without_asking(lc):
    lc.ws.update_config(default_apps=["velora_notify", "velora_search"])
    plane = ControlPlane.open(lc.ws)
    try:
        c = plane.provisioning.provision_company("G", "C", apps=[])["id"]
        t = next(t for t in lifecycle.targets(lc.ws) if t.id == c)
        assert {"velora_notify", "velora_search"} <= set(lifecycle.installed_in(lc.ws, t))
        lc.ws.update_config(default_apps=["no_such_app"])
        with pytest.raises(WorkspaceError, match="Not in this workspace: no_such_app"):
            plane.provisioning.provision_company("G", "D", apps=[])
    finally:
        plane.dispose()


def test_only_the_extras_you_chose_are_kept_current(lc, monkeypatch):
    from velora import optional
    lc.ws.update_config(extras=["sftp", "not_a_real_extra"])
    installed = []
    monkeypatch.setattr(optional, "installed_version", lambda d: None if d == "paramiko" else "99.0")
    monkeypatch.setattr(optional, "install", lambda reqs, **kw: installed.append((list(reqs), kw)))
    logs = []
    done = lifecycle.ensure_all_packages(lc.ws, log=logs.append)
    assert installed == [(["paramiko>=3.4"], {"upgrade": True})] and done == ["paramiko>=3.4"]                          # sftp only: not pdf, not ml, not the unknown one
    assert any("Updating the 'sftp' packages" in l for l in logs)
    lc.ws.update_config(extras=["sftp"])
    monkeypatch.setattr(optional, "install", lambda *a, **k: (_ for _ in ()).throw(optional.DependencyError("no network\nmore")))
    logs.clear()
    assert lifecycle.ensure_all_packages(lc.ws, log=logs.append) == [] and any("Could not update the 'sftp' packages (no network)" in l for l in logs)   # non-fatal


def test_deps_install_remembers_the_extras_in_the_workspace(lc, capsys, monkeypatch):
    from velora import optional
    monkeypatch.setattr(optional, "installed_version", lambda d: None)
    monkeypatch.setattr(optional, "install", lambda reqs, **kw: {"ran": True, "output": ""})
    assert main(["deps", "install", "sftp", "--yes"]) == 0
    assert main(["deps", "install", "pdf", "--yes"]) == 0
    assert lc.ws.common_config()["extras"] == ["pdf", "sftp"]
    assert main(["deps", "install", "--app", "shop", "--yes"]) in (0, None) and lc.ws.common_config()["extras"] == ["pdf", "sftp"]


def test_the_internal_update_step_runs_packages_then_data_then_features(lc, capsys, tmp_path):
    lc.ws.update_config(default_apps=["velora_search"])
    report = tmp_path / "r.json"
    code, out, _ = run(capsys, "apply-update", "--report-file", str(report))
    import json
    rep = json.loads(report.read_text())
    assert code == 0 and rep["status"] in ("success", "up_to_date") and rep["packages"] == [] and [f["app"] for f in rep["features"]] == ["velora_search", "velora_search"]
    assert where(lc, "velora_search") == {lc.a: True, lc.b: True}


# ============================== the self-running server ==============================
@pytest.fixture
def serve(lc, monkeypatch):
    """Run `velora start` with uvicorn replaced by a function that inspects the process while 'serving'."""
    import uvicorn
    from velora.cli import _cmd_start
    seen = {}

    def fake_run(app, host, port, **kw):
        seen["threads"] = [t.name for t in threading.enumerate()]
        seen["during"]()
    monkeypatch.setattr(uvicorn, "run", fake_run)

    def go(during=lambda: None, **flags):
        seen["during"] = during
        _cmd_start(SimpleNamespace(workspace=str(lc.ws.root), site=None, host="127.0.0.1", port=8000, **flags))
        return seen
    return go


def stuck_delivery(lc):
    """A queued email in company A (the worker should pick it up)."""
    run_ = lambda *a: main(list(a))  # noqa: E731
    run_("--company", lc.a, "install-app", "velora_notify", "--no-restart")
    t = next(t for t in lifecycle.targets(lc.ws) if t.id == lc.a)
    with lifecycle.in_target(t):
        d = new_doc("Notification Delivery", rule="r", channel="Email", recipient="a@b.co", subject="s", status="Queued", attempts=0, next_attempt="2020-01-01 00:00:00")
        d.insert(ignore_permissions=True)
    return t, d.name


def status_of(t, name):
    with lifecycle.in_target(t):
        from velora import get_doc
        return get_doc("Notification Delivery", name).status


def test_the_server_runs_its_own_worker_and_stops_it_cleanly(lc, serve):
    t, name = stuck_delivery(lc)

    def during():
        end = time.time() + 15
        while status_of(t, name) == "Queued" and time.time() < end:
            time.sleep(0.2)
    seen = serve(during)
    assert "velora-worker" in seen["threads"]                                                                           # started with the server: no second service
    assert status_of(t, name) in ("Dead", "Sent")                                                                       # and it really did the work (email is not configured: Dead, with a reason)
    time.sleep(0.3)
    assert "velora-worker" not in [x.name for x in threading.enumerate()]                                               # stopped when the server stopped


def test_no_worker_means_no_worker(lc, serve):
    t, name = stuck_delivery(lc)
    seen = serve(lambda: time.sleep(1.0), no_worker=True)
    assert "velora-worker" not in seen["threads"] and status_of(t, name) == "Queued"


def test_a_server_started_on_newer_code_upgrades_the_database_itself_first(lc, serve):
    t = next(t for t in lifecycle.targets(lc.ws) if t.id == lc.b)
    with lifecycle.in_target(t):
        set_setting("framework_version", "0.1.0")                                                                       # this database is older than the code
        t.site.gate_cache = None
    lc.ws.update_config(auto_upgrade=True)
    state = {}

    def during():
        with lifecycle.in_target(t):
            t.site.gate_cache = None
            state["version"] = get_setting("framework_version")
    serve(during, no_worker=True)
    from velora import __version__
    assert state["version"] == __version__                                                                              # upgraded BEFORE serving: nobody sees 'upgrade pending'
    assert list((lc.ws.root / "backups").rglob("*")), "a backup is taken before the automatic upgrade"


def test_automatic_upgrade_on_start_can_be_switched_off(lc, serve):
    t = next(t for t in lifecycle.targets(lc.ws) if t.id == lc.b)
    with lifecycle.in_target(t):
        set_setting("framework_version", "0.1.0")
    lc.ws.update_config(auto_upgrade=True)
    state = {}

    def during():
        with lifecycle.in_target(t):
            state["version"] = get_setting("framework_version")
    serve(during, no_worker=True, auto_upgrade=False)
    assert state["version"] == "0.1.0"                                                                                  # --no-auto-upgrade: left for `velora update`


# ============================== workspace config ==============================
def test_config_updates_merge_remove_and_never_leave_a_temp_file(lc):
    ws = lc.ws
    before = ws.common_config()
    ws.update_config(alpha=1, beta={"x": 1})
    ws.update_config(alpha=2)
    assert ws.common_config() == {**before, "alpha": 2, "beta": {"x": 1}}
    ws.update_config(beta=None, missing=None)
    assert "beta" not in ws.common_config() and ws.common_config()["alpha"] == 2
    assert not list(ws.sites_dir.glob("*.tmp"))


# ============================== doctor: is anything running the worker? ==============================
def worker_checks(lc):
    from velora.upgrade import doctor
    return {c["check"]: c for c in doctor.run_checks(lc.ws) if c["check"].startswith("Background worker")}


def test_doctor_notices_when_nothing_is_running_the_background_worker(lc, capsys):
    from datetime import timedelta
    from sqlalchemy import update

    from velora import db, worker
    from velora.db.system import scheduler_state
    from velora.document.document import now
    assert worker_checks(lc) == {}                                                                                    # nothing installed needs a worker: nothing to say
    run(capsys, "install-app", "velora_notify", "--no-restart")
    checks = worker_checks(lc)
    assert len(checks) == 2 and all(c["status"] == "warn" and "no worker has run for this company yet" in c["detail"] and "velora start" in c["fix"] for c in checks.values())
    worker.run_once(lc.ws)
    checks = worker_checks(lc)
    assert all(c["status"] == "ok" and c["detail"].startswith("last ran ") for c in checks.values())                   # it ran: all well
    for t in lifecycle.targets(lc.ws):                                                                               # twenty minutes ago
        with lifecycle.in_target(t), db.transaction() as c:
            c.execute(update(scheduler_state).where(scheduler_state.c.key == "every_minute").values(last_run=now() - timedelta(minutes=20)))
    checks = worker_checks(lc)
    assert all(c["status"] == "warn" and "in 20 minutes" in c["detail"] for c in checks.values())


# ============================== an explicit uninstall is remembered ==============================
def test_uninstalling_a_default_app_everywhere_stops_update_from_bringing_it_back(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    lc.ws.update_config(default_apps=["velora_notify", "velora_search"])
    run(capsys, "update")
    assert where(lc, "velora_search") == {lc.a: True, lc.b: True}
    assert run(capsys, "uninstall-app", "velora_search", "--yes", "--no-restart")[0] == 0
    assert lc.ws.common_config()["default_apps"] == ["velora_notify"]                                                 # no longer a default
    code, out, _ = run(capsys, "update")
    assert code == 0 and "Enabled" not in out and where(lc, "velora_search") == {lc.a: False, lc.b: False}            # and update leaves it off
    assert where(lc, "velora_notify") == {lc.a: True, lc.b: True}                                                     # the others are untouched


def test_removing_it_from_one_company_is_remembered_for_that_company_only(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    lc.ws.update_config(default_apps=["velora_search"])
    run(capsys, "update")
    assert run(capsys, "--company", lc.a, "uninstall-app", "velora_search", "--yes", "--no-restart")[0] == 0
    assert lc.ws.common_config()["default_apps"] == ["velora_search"] and lc.ws.common_config()["default_apps_skip"] == {"velora_search": [lc.a]}
    assert "Enabled" not in run(capsys, "update")[1] and where(lc, "velora_search") == {lc.a: False, lc.b: True}
    plane = ControlPlane.open(lc.ws)                                                                                   # a NEW company still gets the default
    try:
        c = plane.provisioning.provision_company("G", "C", apps=[])["id"]
    finally:
        plane.dispose()
    assert where(lc, "velora_search")[c] is True


def test_installing_it_again_clears_the_opt_out(lc, capsys, monkeypatch):
    from velora.upgrade import update as upd
    monkeypatch.setattr(upd, "framework_latest", lambda source: None)
    lc.ws.update_config(default_apps=["velora_search"])
    run(capsys, "update")
    run(capsys, "--company", lc.a, "uninstall-app", "velora_search", "--yes", "--no-restart")
    assert run(capsys, "--company", lc.a, "install-app", "velora_search", "--no-restart")[0] == 0
    assert "default_apps_skip" not in lc.ws.common_config() and where(lc, "velora_search") == {lc.a: True, lc.b: True}


def test_a_failed_or_non_default_uninstall_changes_no_settings(lc, capsys):
    lc.ws.update_config(default_apps=["velora_notify"])
    run(capsys, "install-app", "shop", "--no-restart")
    assert run(capsys, "uninstall-app", "shop", "--yes", "--no-restart")[0] == 0
    assert lc.ws.common_config()["default_apps"] == ["velora_notify"] and "default_apps_skip" not in lc.ws.common_config()      # shop was never a default
    assert run(capsys, "uninstall-app", "velora_notify", "--yes", "--no-restart")[1].count("is not installed") == 1                 # nothing to remove: no change either
    assert lc.ws.common_config()["default_apps"] == ["velora_notify"]


def test_doctor_never_reports_that_it_could_not_inspect_something(lc, capsys):
    """Regression: the PostgreSQL check once crashed on the control plane (it has no site) and showed 'could not inspect: AttributeError'."""
    from velora.upgrade import doctor
    run(capsys, "install-app", "velora_notify", "--no-restart")
    checks = doctor.run_checks(lc.ws)
    assert not [c for c in checks if "could not inspect" in c["detail"]], [c for c in checks if "could not inspect" in c["detail"]]
    assert not [c for c in checks if c["status"] == "fail"]
    pg = [c for c in checks if c["check"].startswith("PostgreSQL ")]
    assert all(c["status"] in ("ok", "warn") and "version" in c["detail"] for c in pg)                                  # only real servers are listed, each with its version


def test_a_command_needs_no_company_flag_when_there_is_only_one_company(lc, capsys):
    code, _, err = run(capsys, "doctypes")
    assert code == 1 and f"has 2 companies ({lc.a}, {lc.b})" in err and "--company ID" in err                           # ambiguous: it says how to choose, it does not guess
    assert run(capsys, "--company", lc.a, "doctypes")[0] == 0
    plane = ControlPlane.open(lc.ws)
    plane.provisioning.drop_company(lc.b, root_password=PGROOT)
    plane.dispose()
    code, out, err = run(capsys, "doctypes")
    assert code == 0 and not err                                                                                        # exactly one company left: no flag needed


def test_app_requiring_an_incompatible_framework_version_is_rejected_before_install(lc, capsys):
    src = ext_app(lc.tmp, "oldframeworkapp", "OldFrameworkThing", hooks='required_velora = "<0.1"\n')
    code, out, err = run(capsys, "install-app", str(src), "--no-restart")
    assert code == 1
    assert "requires Velora <0.1" in out + err
    assert where(lc, "oldframeworkapp") == {lc.a: False, lc.b: False}
