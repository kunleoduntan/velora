import json
import os
import sys
import threading
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import velora
from velora import db, scheduler, worker
from velora.cli import main
from velora.controlplane import ControlPlane
from velora.scaffold import new_app
from velora.settings import get_setting, set_setting
from velora.upgrade import maintenance
from velora.workspace import Workspace
from upgrade_helpers import PW, clean_modules, make_app

T0 = datetime(2026, 3, 1, 12, 0, 0)
JOBS = '''
import velora
from velora.settings import set_setting, get_setting
CALLS = []

def tick():            CALLS.append("tick")
def minute():          CALLS.append("minute")
def hourly():          CALLS.append("hourly")
def daily():           CALLS.append("daily")
def boom():
    set_setting("sched.partial", "written then rolled back")
    raise RuntimeError("this task is broken")
def after_boom():
    set_setting("sched.after", "ran")
def who():
    c = velora.current_company()
    CALLS.append(c.id if c else "single-site")
'''


def write_hooks(root, name, events):
    pkg = root / name
    (pkg / "jobs.py").write_text(JOBS)
    h = pkg / "hooks.py"
    h.write_text(h.read_text() + f"\nscheduler_events = {json.dumps(events)}\n")


def _urls():
    return ["sqlite"] + (["postgres"] if os.environ.get("VELORA_TEST_PG_URL") else [])


@pytest.fixture(params=_urls())
def sched(request, tmp_path):
    name = "sched_" + uuid.uuid4().hex[:8]
    root = new_app(tmp_path, name, module="Sched")
    write_hooks(root, name, {"every_tick": [f"{name}.jobs.tick"], "every_minute": [f"{name}.jobs.minute"], "hourly": [f"{name}.jobs.hourly"], "daily": [f"{name}.jobs.daily"],
                             "weekly": [f"{name}.jobs.tick"]})                                  # an unknown frequency is simply never run
    before_path, before_mods = list(sys.path), set(sys.modules)
    sys.path.insert(0, str(root))
    url = f"sqlite:///{tmp_path / 's.db'}" if request.param == "sqlite" else os.environ["VELORA_TEST_PG_URL"]
    velora.init(velora.configure(db_url=url, apps=[name], developer_mode=True))
    if request.param == "postgres":                                                                                  # clean slate on the shared database
        from sqlalchemy import MetaData
        with db.transaction() as conn:
            md = MetaData()
            md.reflect(conn)
            md.drop_all(conn)
    velora.migrate()
    import importlib
    jobs = importlib.import_module(f"{name}.jobs")
    yield SimpleNamespace(name=name, jobs=jobs, root=root)
    velora.shutdown()
    clean_modules(tmp_path, before_path, before_mods)


def freqs(results):
    return [r["freq"] for r in results]


def test_each_frequency_runs_when_due_and_not_before(sched):
    r = scheduler.run_due(T0)
    assert freqs(r) == ["every_tick", "every_minute", "hourly", "daily"] and all(x["ok"] for x in r)             # first pass: everything is due
    assert freqs(scheduler.run_due(T0 + timedelta(seconds=30))) == ["every_tick"]                                  # 30 s later: only the per-tick tasks
    assert freqs(scheduler.run_due(T0 + timedelta(seconds=61))) == ["every_tick", "every_minute"]
    assert freqs(scheduler.run_due(T0 + timedelta(minutes=59))) == ["every_tick", "every_minute"]
    assert freqs(scheduler.run_due(T0 + timedelta(minutes=61))) == ["every_tick", "every_minute", "hourly"]
    assert freqs(scheduler.run_due(T0 + timedelta(hours=25))) == ["every_tick", "every_minute", "hourly", "daily"]
    assert sched.jobs.CALLS.count("daily") == 2 and "weekly" not in freqs(scheduler.run_due(T0 + timedelta(days=9)))


def test_a_frequency_is_claimed_atomically_so_it_runs_once_per_interval(sched):
    assert scheduler.claim("hourly", T0) is True
    assert scheduler.claim("hourly", T0) is False and scheduler.claim("hourly", T0 + timedelta(minutes=59)) is False
    assert scheduler.claim("hourly", T0 + timedelta(minutes=60)) is True
    assert scheduler.claim("every_tick", T0) is True and scheduler.claim("every_tick", T0) is True               # per-tick work is never "claimed"


def test_a_broken_task_is_reported_and_neither_stops_the_others_nor_leaves_half_written_data(sched):
    from velora.meta.registry import registry
    registry._scheduler["every_tick"] = [f"{sched.name}.jobs.boom", f"{sched.name}.jobs.after_boom", f"{sched.name}.jobs.no_such_function", "not.a.module.fn"]
    r = scheduler.run_due(T0)
    tick = [x for x in r if x["freq"] == "every_tick"]
    assert [x["ok"] for x in tick] == [False, True, False, False]
    assert "RuntimeError: this task is broken" in tick[0]["error"] and "no_such_function" in tick[2]["error"]
    assert get_setting("sched.partial") is None                                                                    # the failed task's own write was rolled back
    assert get_setting("sched.after") == "ran"                                                                     # the next task still ran and committed


def test_concurrent_workers_claim_a_frequency_exactly_once(sched):
    from velora.db import get_engine
    if get_engine().dialect.name != "postgresql":
        pytest.skip("SQLite serialises writers; the race is verified on PostgreSQL")
    assert scheduler.claim("hourly", T0 - timedelta(hours=2)) is True                                              # an old claim exists: now the hourly slot is due again
    wins = []

    def go(i):
        wins.append(scheduler.claim("hourly", T0, owner=f"w{i}"))
    ts = [threading.Thread(target=go, args=(i,)) for i in range(10)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert wins.count(True) == 1 and wins.count(False) == 9


# ======================= the worker across a workspace of companies =======================
def build_ws(tmp_path, monkeypatch, events):
    for k in ("VELORA_MASTER_KEY", "VELORA_WORKSPACE", "VELORA_SITE"):
        monkeypatch.delenv(k, raising=False)
    before_path, before_mods = list(sys.path), set(sys.modules)
    ws = Workspace.create(tmp_path / "ws")
    monkeypatch.chdir(ws.root)
    root = make_app(ws)
    write_hooks(root, "shop", events)
    plane = ControlPlane.create(ws, admin_email="root@example.com", admin_password=PW)
    plane.registry.create_tenant("G")
    a = plane.provisioning.provision_company("G", "A", apps=["shop"])["id"]
    b = plane.provisioning.provision_company("G", "B", apps=["shop"])["id"]
    import importlib
    return SimpleNamespace(ws=ws, plane=plane, a=a, b=b, jobs=importlib.import_module("shop.jobs")), lambda: (plane.dispose(), clean_modules(tmp_path, before_path, before_mods))


@pytest.fixture
def wsenv(tmp_path, monkeypatch):
    env, cleanup = build_ws(tmp_path, monkeypatch, {"every_tick": ["shop.jobs.who"], "every_minute": ["shop.jobs.minute"]})
    yield env
    cleanup()


@pytest.fixture
def wsbroken(tmp_path, monkeypatch):
    env, cleanup = build_ws(tmp_path, monkeypatch, {"every_tick": ["shop.jobs.who"], "hourly": ["shop.jobs.boom"]})
    yield env
    cleanup()


def test_the_worker_runs_every_company_inside_that_company(wsenv):
    res = worker.run_once(wsenv.ws, T0)
    assert sorted(r["target"] for r in res) == [wsenv.a, wsenv.b] and all(x["ok"] for r in res for x in r["results"])
    assert sorted(wsenv.jobs.CALLS) == ["COMP-001", "COMP-002", "minute", "minute"]                                  # the job saw ITS company each time
    wsenv.jobs.CALLS.clear()
    worker.run_once(wsenv.ws, T0 + timedelta(seconds=10))
    assert sorted(wsenv.jobs.CALLS) == ["COMP-001", "COMP-002"]                                                      # each company's schedule is tracked separately


def test_the_worker_leaves_a_company_alone_while_its_database_needs_an_upgrade(wsenv):
    with wsenv.plane.company_scope(wsenv.b) as site:
        set_setting("framework_version", "0.1.0")
        site.gate_cache = None
    res = worker.run_once(wsenv.ws, T0)
    assert [r["target"] for r in res] == [wsenv.a]                                                                  # new code must not run against an old database


def test_the_worker_pauses_during_maintenance(wsenv, capsys):
    maintenance.enable(wsenv.ws)
    assert worker.run_once(wsenv.ws, T0) == []
    maintenance.disable(wsenv.ws)
    assert main(["worker", "--once"]) == 0 and "Ran 4 task(s) across 2 database(s)." in capsys.readouterr().out


def test_a_failing_job_is_logged_with_its_company_and_the_cli_exits_non_zero(wsbroken, capsys):
    msgs = []
    res = worker.run_once(wsbroken.ws, T0, log=msgs.append)
    bad = [x for r in res for x in r["results"] if not x["ok"]]
    assert len(bad) == 2 and all("RuntimeError: this task is broken" in x["error"] for x in bad)                    # once per company
    assert len(msgs) == 2 and msgs[0].startswith("COMP-001 A: shop.jobs.boom failed: RuntimeError") and wsbroken.jobs.CALLS.count("COMP-001") == 1       # ... and the healthy job still ran
    assert main(["worker", "--once"]) == 1                                                                         # the real clock makes the hourly job due again: it fails, so the CLI exits non-zero
    assert "Ran" in capsys.readouterr().out
