"""What Velora runs on: Python, PostgreSQL and operating systems, from one module."""
import os
from types import SimpleNamespace

import pytest

import velora
from velora import compat, db, pg
from velora.db import get_engine

from test_notify import ns  # noqa: F401


@pytest.mark.parametrize("v,status", [((3, 6, 9), "fail"), ((3, 8, 10), "fail"), ((3, 9, 18), "fail"), ((3, 10, 0), "ok"), ((3, 10, 20), "ok"), ((3, 11, 2), "ok"), ((3, 12, 3), "ok"), ((3, 13, 1), "ok"), ((3, 14, 0), "ok")])
def test_python_versions(v, status):
    st, detail, fix = compat.python_status(v)
    assert st == status and detail == ".".join(map(str, v))
    assert (fix == "") == (status == "ok") and (status == "ok" or "3.10 or newer" in fix and "private one" in fix)


def test_this_very_interpreter_is_supported_and_the_package_says_the_same():
    assert compat.python_status()[0] == "ok"
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    from pathlib import Path
    meta = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text())["project"]
    assert meta["requires-python"] == f">={compat.MIN_PYTHON[0]}.{compat.MIN_PYTHON[1]}"                                  # one number, two places: they must agree
    acc = tomllib.loads((Path(__file__).parent.parent / "apps" / "velora_accounts" / "pyproject.toml").read_text())["project"]
    assert acc["requires-python"] == meta["requires-python"]
    assert any(d.startswith("tomli") and "python_version < " in d for d in meta["dependencies"])                       # Python 3.10 needs it


OS = lambda i, v, pretty="": {"ID": i, "VERSION_ID": v, "PRETTY_NAME": pretty or f"{i} {v}"}  # noqa: E731


@pytest.mark.parametrize("info,status,frag", [
    (OS("ubuntu", "18.04"), "eol", "End of life since 2023"), (OS("ubuntu", "20.04"), "works", "official PostgreSQL repository"), (OS("ubuntu", "22.04"), "supported", "Python 3.10 (works as is)"),
    (OS("ubuntu", "24.04"), "supported", "The system the test suite ran on"), (OS("ubuntu", "26.04"), "supported", "PostgreSQL 18"),
    (OS("debian", "11"), "works", "private Python"), (OS("debian", "12"), "supported", "PostgreSQL 15"), (OS("debian", "13"), "supported", "PostgreSQL 17"),
    (OS("ubuntu", "16.04"), "untested", "has not been checked"), (OS("ubuntu", "28.04"), "untested", "has not been checked"), (OS("debian", "9"), "untested", "has not been checked"),
    (OS("fedora", "40"), "untested", "supports Ubuntu and Debian"), ({}, "untested", "supports Ubuntu and Debian")])
def test_each_operating_system_is_classified_with_an_honest_note(info, status, frag):
    r = compat.os_support(info)
    assert r["status"] == status and frag in r["note"] and r["name"]


def test_18_04_is_never_called_supported_for_a_server():
    assert compat.os_support(OS("ubuntu", "18.04"))["status"] == "eol" and "do-release-upgrade" in compat.os_support(OS("ubuntu", "18.04"))["note"]


def test_os_release_files_are_parsed_including_quotes_and_comments():
    txt = 'NAME="Ubuntu"\nVERSION_ID="22.04"\n# a comment\nPRETTY_NAME="Ubuntu 22.04.5 LTS"\nID=ubuntu\nVERSION_CODENAME=jammy\n\nbroken line\n'
    assert compat.parse_os_release(txt) == {"NAME": "Ubuntu", "VERSION_ID": "22.04", "PRETTY_NAME": "Ubuntu 22.04.5 LTS", "ID": "ubuntu", "VERSION_CODENAME": "jammy"}
    assert compat.os_support(compat.parse_os_release(txt))["status"] == "supported" and compat.parse_os_release("") == {}


@pytest.mark.parametrize("num,status", [(100023, "fail"), (110022, "fail"), (120018, "fail"), (130016, "warn"), (140013, "warn"), (150008, "ok"), (160015, "ok"), (170005, "ok"), (180001, "ok")])
def test_postgres_versions(num, status):
    st, detail, fix = compat.postgres_status(num)
    assert st == status and detail == str(num // 10000)
    if status == "fail":
        assert "needs PostgreSQL 13 or newer" in fix and "apt.postgresql.org" in fix
        with pytest.raises(compat.UnsupportedPostgres, match=f"version {num // 10000}, which is too old"):
            compat.require_postgres(num)
    else:
        compat.require_postgres(num)                                                                                    # 13 and 14 still work; they are only advised about
    assert (status != "warn") or "plan an upgrade" in fix


def test_migrate_refuses_an_old_postgres_before_touching_anything(ns, monkeypatch):
    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL only")
    orig = compat.require_postgres
    monkeypatch.setattr(compat, "require_postgres", lambda n: orig(120018))                                            # pretend the server reports PostgreSQL 12
    with pytest.raises(compat.UnsupportedPostgres, match="PostgreSQL server is version 12, which is too old"):
        velora.migrate()
    monkeypatch.setattr(compat, "require_postgres", orig)
    assert velora.migrate() == []                                                                                       # and the real server is fine


def test_the_check_is_a_no_op_on_other_databases(ns):
    if get_engine().dialect.name == "postgresql":
        pytest.skip("SQLite only")
    with get_engine().connect() as c:
        pg.require_supported(c)


def test_pg_status_advises_per_the_same_rules(ns, monkeypatch):
    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL only")
    with get_engine().connect() as c:
        real = c.exec_driver_sql
        fake = SimpleNamespace(dialect=c.dialect, exec_driver_sql=lambda sql, *a, **k: SimpleNamespace(scalar=lambda: 140013) if "server_version_num" in sql else real(sql, *a, **k), execute=c.execute)
        adv = pg.status(fake)["advice"]
    assert any("PostgreSQL 14 works but is near the end of its support" in a for a in adv)


def test_doctor_reports_the_python_and_the_operating_system(tmp_path, monkeypatch):
    from velora.upgrade import doctor
    from velora.workspace import Workspace
    ws = Workspace.create(tmp_path / "w")
    checks = {c["check"]: c for c in doctor.run_checks(ws)}
    assert checks["Python"]["status"] == "ok" and checks["Operating system"]["detail"].endswith(")")
    monkeypatch.setattr(compat, "current_os", lambda: compat.os_support(OS("ubuntu", "18.04")))
    c = {x["check"]: x for x in doctor.run_checks(ws)}["Operating system"]
    assert c["status"] == "warn" and "(eol)" in c["detail"] and "do-release-upgrade" in c["fix"]
    monkeypatch.setattr(compat, "python_status", lambda v=None: ("fail", "3.9.1", "Velora needs Python 3.10 or newer"))
    assert {x["check"]: x for x in doctor.run_checks(ws)}["Python"]["status"] == "fail"
