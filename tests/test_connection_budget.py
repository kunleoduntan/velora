import pytest
from sqlalchemy.exc import OperationalError

from velora import dbpool


def test_defaults_fit_a_default_postgres():
    s = dbpool.settings()
    assert dbpool.worst_case(s) <= s["connection_budget"] <= 97          # PostgreSQL default is 100 with 3 reserved


@pytest.mark.parametrize("budget", [11, 20, 48, 100, 500])
def test_worst_case_never_exceeds_budget(budget):
    s = dbpool.settings(overrides={"connection_budget": budget})
    assert dbpool.worst_case(s) <= budget
    assert dbpool.max_company_pools(s) >= 1


@pytest.mark.parametrize("bad", [{"connection_budget": 10}, {"company_pool_size": 0}, {"pool_timeout": -1}, {"company_pool_size": True}, {"company_pool_size": "3"}, {"nonsense": 1}])
def test_bad_settings_are_refused(bad):
    with pytest.raises(dbpool.PoolSettingError):
        dbpool.settings(overrides=bad)


def test_settings_read_from_workspace_config(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "common.json").write_text('{"db_pool": {"connection_budget": 30}}')
    assert dbpool.settings(tmp_path)["connection_budget"] == 30


def test_connections_are_labelled():
    kw = dbpool.company_kwargs(dbpool.settings(), "COMP-001")
    assert kw["connect_args"]["application_name"].startswith("velora:company:COMP-001:")
    assert len(kw["connect_args"]["application_name"]) <= 63


def test_exhaustion_is_recognised():
    assert dbpool.is_connection_exhaustion(Exception("FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute"))
    assert dbpool.is_connection_exhaustion(Exception("sorry, too many clients already"))
    assert not dbpool.is_connection_exhaustion(Exception("password authentication failed"))


def test_router_pool_count_follows_budget(site):
    from velora.controlplane.router import DatabaseRouter

    class P:
        db_settings = dbpool.settings(overrides={"connection_budget": 20})
    r = DatabaseRouter(P())
    assert r.max_pools * (r.pool_size + r.max_overflow) + 5 <= 20


def test_cli_prints_one_sentence_for_exhaustion(monkeypatch, capsys):
    from velora import cli
    err = OperationalError("x", {}, Exception("FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute"))
    monkeypatch.setitem(cli.COMMANDS, "doctor", lambda a: (_ for _ in ()).throw(err))
    monkeypatch.delenv("VELORA_DEBUG", raising=False)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().err
    assert "no free connection slots" in out and "Traceback" not in out


def test_api_answers_503_when_pool_is_exhausted():
    import asyncio
    from sqlalchemy.exc import TimeoutError as PoolTimeout
    from velora.api.app import create_app
    handler = create_app(auto_init=False).exception_handlers[PoolTimeout]
    r = asyncio.run(handler(None, PoolTimeout("QueuePool limit reached")))
    assert r.status_code == 503 and r.headers["retry-after"] == "5" and b"DatabaseBusy" in r.body
    r = asyncio.run(create_app(auto_init=False).exception_handlers[OperationalError](None, OperationalError("x", {}, Exception("connection refused"))))
    assert r.status_code == 503 and b"DatabaseUnavailable" in r.body
