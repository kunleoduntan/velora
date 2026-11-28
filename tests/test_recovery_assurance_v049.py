"""Restore rehearsals: what they verify, what they record, and that they always clean up. Unit tests use a scripted runner; the integration tests use a real PostgreSQL."""
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import velora.recovery_assurance as ra
from velora.recovery_assurance import RecoveryRehearsalError, record_rehearsal, recovery_assurance_report, rehearse_postgres_restore

LISTING = """;
; Archive created at 2026-11-10 10:00:00 UTC
201; 1259 16401 TABLE public tab_customer velora
202; 1259 16410 TABLE public tab_invoice velora
301; 0 16401 TABLE DATA public tab_customer velora
302; 0 16410 TABLE DATA public tab_invoice velora
"""
PSQL_OK = "T|public|tab_customer|\nT|public|tab_invoice|\nT|public|extra|\nD|public|tab_customer|rows\nD|public|tab_invoice|rows\n"
URL = "postgresql://dr_user:s3cret@db.example:5433/prod?sslmode=require"


class Out:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class Script:
    """A scripted runner: answers by program name, remembers every call and the environment it was given."""

    def __init__(self, **answers):
        self.answers, self.calls, self.envs = answers, [], []

    def __call__(self, args, **kw):
        self.calls.append(list(args)); self.envs.append(kw.get("env"))
        answer = self.answers.get(args[0] if args[0] != "pg_restore" else ("pg_restore_list" if "--list" in args else "pg_restore"), Out())
        if isinstance(answer, Exception):
            raise answer
        return answer

    def names(self):
        return [c[0] if c[0] != "pg_restore" else ("pg_restore --list" if "--list" in c else "pg_restore") for c in self.calls]


@pytest.fixture
def backup(tmp_path, monkeypatch):
    f = tmp_path / "dump.backup"; f.write_bytes(b"PGDMP-test")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    return f


def rehearse(backup, runner, **kw):
    return rehearse_postgres_restore(backup, database_url=URL, runner=runner, **kw)


# ============================== the happy path, and what is checked ==============================
def test_a_rehearsal_creates_restores_verifies_and_drops_in_that_order(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout=PSQL_OK))
    r = rehearse(backup, run)
    assert run.names() == ["pg_restore --list", "createdb", "pg_restore", "psql", "dropdb"]
    scratch = r["scratch_database"]
    assert scratch.startswith("velora_rehearsal_") and run.calls[2][run.calls[2].index("--dbname") + 1] == scratch and run.calls[3][run.calls[3].index("--dbname") + 1] == scratch
    assert r["status"] == "passed" and r["verified"] is True and r["cleanup_completed"] is True
    assert r["verification"]["tables_expected"] == 2 and r["verification"]["tables_restored"] == 2 and r["verification"]["missing_tables"] == []
    assert r["backup_bytes"] == 10 and r["backup_age_hours"] >= 0


def test_the_child_programs_get_database_settings_but_never_the_frameworks_secrets(backup, monkeypatch):
    monkeypatch.setenv("VELORA_MASTER_KEY", "master-secret"); monkeypatch.setenv("VELORA_BACKUP_PASSWORD", "backup-secret"); monkeypatch.setenv("VELORA_ANYTHING", "x")
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout=PSQL_OK))
    rehearse(backup, run)
    for env in run.envs:
        assert not [k for k in env if k.startswith("VELORA_")]
        assert (env["PGHOST"], env["PGPORT"], env["PGUSER"], env["PGPASSWORD"], env["PGSSLMODE"]) == ("db.example", "5433", "dr_user", "s3cret", "require")
        assert "PATH" in env                                                                  # ... and everything else they need still arrives


def test_a_table_the_archive_promised_but_the_restore_did_not_produce_fails_the_rehearsal(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout="T|public|tab_customer|\nD|public|tab_customer|rows\n"))
    with pytest.raises(RecoveryRehearsalError, match="missing after the restore") as e:
        rehearse(backup, run)
    r = e.value.result
    assert r["status"] == "failed" and r["verified"] is False and r["verification"]["missing_tables"] == ["public.tab_invoice"]
    assert run.names()[-1] == "dropdb" and r["cleanup_completed"] is True                      # and it still cleaned up


def test_an_archive_with_no_tables_is_not_a_backup_of_anything(backup):
    run = Script(pg_restore_list=Out(stdout=";\n; empty archive\n"))
    with pytest.raises(RecoveryRehearsalError, match="lists no tables") as e:
        rehearse(backup, run)
    assert e.value.result["status"] == "failed" and run.names() == ["pg_restore --list"]       # never even created a database


def test_empty_tables_are_reported_but_are_not_a_failure(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout="T|public|tab_customer|\nT|public|tab_invoice|\nD|public|tab_customer|rows\nD|public|tab_invoice|empty\n"))
    r = rehearse(backup, run)
    assert r["status"] == "passed" and r["verification"]["empty_data_table_count"] == 1 and r["verification"]["empty_data_tables"] == ["public.tab_invoice"]


def test_without_psql_the_rehearsal_says_honestly_that_it_did_not_inspect_the_result(backup, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "psql" else "/usr/bin/" + name)
    run = Script(pg_restore_list=Out(stdout=LISTING))
    r = rehearse(backup, run)
    assert r["status"] == "passed" and r["verified"] is False and "not inspected" in r["verification"]["note"] and "psql" not in run.names()


def test_a_failed_inspection_fails_the_rehearsal(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(returncode=2, stderr="FATAL: the database system is shutting down"))
    with pytest.raises(RecoveryRehearsalError, match="Could not inspect"):
        rehearse(backup, run)
    assert run.names()[-1] == "dropdb"


# ============================== failure handling ==============================
def test_a_bad_archive_is_recorded_as_a_failed_rehearsal(backup):
    with pytest.raises(RecoveryRehearsalError, match="not a readable pg_restore archive") as e:
        rehearse(backup, Script(pg_restore_list=Out(1, stderr="invalid archive")))
    assert e.value.result["status"] == "failed" and "invalid archive" in e.value.result["error"]


def test_setup_problems_are_not_rehearsals_and_carry_no_result(tmp_path, backup, monkeypatch):
    with pytest.raises(RecoveryRehearsalError, match="not found") as e:
        rehearse(tmp_path / "missing.backup", Script())
    assert e.value.result is None
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "dropdb" else "/usr/bin/" + name)
    with pytest.raises(RecoveryRehearsalError, match="utility not found: dropdb") as e:
        rehearse(backup, Script())
    assert e.value.result is None
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name)
    with pytest.raises(RecoveryRehearsalError, match="PostgreSQL connection URL"):
        rehearse_postgres_restore(backup, database_url="mysql://u@h/db", runner=Script())


def test_a_timeout_anywhere_is_a_clean_failure_and_the_scratch_database_is_still_dropped(backup):
    slow = subprocess.TimeoutExpired("x", 5)
    with pytest.raises(RecoveryRehearsalError, match="timed out after 5 seconds") as e:
        rehearse(backup, Script(pg_restore_list=slow), timeout=5)                              # the very first call: used to be an unhandled crash
    assert e.value.result["status"] == "failed"
    run = Script(pg_restore_list=Out(stdout=LISTING), pg_restore=slow)
    with pytest.raises(RecoveryRehearsalError, match="timed out"):
        rehearse(backup, run, timeout=5)
    assert run.names() == ["pg_restore --list", "createdb", "pg_restore", "dropdb"]
    run = Script(pg_restore_list=Out(stdout=LISTING), createdb=slow)
    with pytest.raises(RecoveryRehearsalError, match="timed out"):
        rehearse(backup, run, timeout=5)
    assert run.names()[-1] == "dropdb"                                                         # a killed createdb may still have created it on the server


def test_a_database_that_cannot_be_dropped_is_reported_with_its_name(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout=PSQL_OK), dropdb=subprocess.TimeoutExpired("dropdb", 5))
    with pytest.raises(RecoveryRehearsalError, match="must be removed by hand: velora_rehearsal_") as e:
        rehearse(backup, run, timeout=5)
    assert e.value.result["cleanup_completed"] is False and "timed out" in e.value.result["cleanup_error"]
    assert e.value.result["scratch_database"] in str(e.value)


def test_a_program_that_cannot_start_is_a_clean_failure(backup):
    with pytest.raises(RecoveryRehearsalError, match="No such file"):
        rehearse(backup, Script(pg_restore_list=FileNotFoundError("No such file or directory: pg_restore")))


def test_a_restore_error_still_drops_and_explains(backup):
    run = Script(pg_restore_list=Out(stdout=LISTING), pg_restore=Out(1, stderr="pg_restore: error: could not execute query"))
    with pytest.raises(RecoveryRehearsalError, match="restore rehearsal failed: pg_restore: error") as e:
        rehearse(backup, run)
    assert run.names() == ["pg_restore --list", "createdb", "pg_restore", "dropdb"] and e.value.result["cleanup_completed"] is True


# ============================== timing ==============================
def test_recovery_time_is_create_plus_restore_plus_verify_and_never_includes_cleanup(backup, monkeypatch):
    clock = iter([0.0, 2.0, 2.0, 12.0, 12.0, 13.0, 99.0, 99.0])                              # create 2 s, restore 10 s, verify 1 s; whatever happens after is cleanup
    monkeypatch.setattr(ra.time, "monotonic", lambda: next(clock))
    r = rehearse(backup, Script(pg_restore_list=Out(stdout=LISTING), psql=Out(stdout=PSQL_OK)))
    assert (r["createdb_seconds"], r["restore_duration_seconds"], r["verify_seconds"], r["recovery_seconds"]) == (2.0, 10.0, 1.0, 13.0)


# ============================== the evidence report ==============================
NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def rec(status="passed", days_ago=1, **kw):
    return {"status": status, "tested_at": (NOW - timedelta(days=days_ago)).isoformat(), "kind": "postgresql_restore_rehearsal", **kw}


def report(tmp_path, *records, raw=""):
    for r in records:
        record_rehearsal(tmp_path, r)
    if raw:
        with (tmp_path / "logs" / "recovery-rehearsals.jsonl").open("a") as f:
            f.write(raw)
    return recovery_assurance_report(tmp_path, now=NOW)


def test_with_no_rehearsals_there_is_no_assurance(tmp_path):
    r = recovery_assurance_report(tmp_path, now=NOW)
    assert r["assurance"] == "none" and r["stale"] is True and r["measured_rto_seconds"] is None and r["rehearsals_total"] == 0


def test_the_latest_failure_is_visible_and_counted(tmp_path):
    r = report(tmp_path, rec(days_ago=9, verified=True, recovery_seconds=30), rec("failed", 2, error="boom"), rec("failed", 1, error="again"))
    assert r["assurance"] == "failing" and r["consecutive_failures"] == 2 and r["rehearsals_total"] == 3 and r["rehearsals_passed"] == 1
    assert r["latest_rehearsal"]["error"] == "again"


def test_an_old_pass_is_stale_however_good_it_was(tmp_path):
    assert report(tmp_path, rec(days_ago=36, verified=True, recovery_seconds=30))["assurance"] == "stale"
    assert recovery_assurance_report(tmp_path, now=NOW, stale_after_days=60)["assurance"] == "current"


def test_a_pass_that_did_not_inspect_the_result_is_called_unverified(tmp_path):
    assert report(tmp_path, rec(days_ago=1, verified=False, recovery_seconds=30))["assurance"] == "unverified"


def test_records_from_before_verification_existed_are_not_called_unverified(tmp_path):
    r = report(tmp_path, rec(days_ago=3, restore_duration_seconds=12.5))                    # the old format: no "verified", no "recovery_seconds"
    assert r["assurance"] == "current" and r["measured_rto_seconds"] == 12.5 and "not inferred" in r["rpo_measurement"]


def test_the_recovery_time_quoted_is_the_worst_of_the_recent_passes_not_the_luckiest(tmp_path):
    r = report(tmp_path, *[rec(days_ago=10 - i, verified=True, recovery_seconds=s) for i, s in enumerate([500, 40, 35, 60, 30, 45])])
    assert r["measured_rto_seconds"] == 60 and r["median_recovery_seconds"] == 40 and "slowest of the last 5" in r["rto_basis"]       # the 500 s run is outside the last five
    assert r["rehearsals_verified"] == 6


def test_damaged_log_lines_are_counted_not_ignored_silently(tmp_path):
    r = report(tmp_path, rec(days_ago=1, verified=True, recovery_seconds=5), raw="{ not json\n\n{\"status\": \"passed\"\n")
    assert r["corrupt_log_lines"] == 2 and r["rehearsals_total"] == 1 and r["assurance"] == "current"


def test_a_pass_with_an_unreadable_date_cannot_claim_to_be_current(tmp_path):
    assert report(tmp_path, {"status": "passed", "tested_at": "yesterday-ish", "verified": True})["assurance"] == "stale"


# ============================== for real, against PostgreSQL ==============================
PG_URL = os.environ.get("VELORA_TEST_PG_URL")
real = pytest.mark.skipif(not PG_URL or not all(shutil.which(x) for x in ("pg_dump", "pg_restore", "createdb", "dropdb", "psql")), reason="needs PostgreSQL and its client programs")


def pg(*args, url=None):
    base = (url or PG_URL).replace("postgresql+psycopg", "postgresql")
    env = ra._pg_environment(base)
    return subprocess.run(list(args), capture_output=True, text=True, env=env, timeout=60)


def orphans():
    return [x for x in pg("psql", "-X", "-At", "--dbname", "postgres", "-c", "SELECT datname FROM pg_database WHERE datname LIKE 'velora_rehearsal_%'").stdout.split() if x]


@pytest.fixture
def source_dump(tmp_path):
    name = "velora_dr_source"
    pg("dropdb", "--if-exists", "--maintenance-db=postgres", name)
    assert pg("createdb", "--maintenance-db=postgres", name).returncode == 0
    sql = ("CREATE TABLE tab_customer (name text primary key, credit numeric); INSERT INTO tab_customer SELECT 'c' || g, g * 1.5 FROM generate_series(1, 500) g;"
           "CREATE TABLE tab_invoice (id serial primary key, customer text references tab_customer(name), total numeric); INSERT INTO tab_invoice (customer, total) SELECT 'c' || g, g FROM generate_series(1, 500) g;"
           "CREATE TABLE tab_empty (id int); CREATE INDEX ON tab_invoice (customer);")
    assert pg("psql", "-X", "-v", "ON_ERROR_STOP=1", "--dbname", name, "-c", sql).returncode == 0
    dump = tmp_path / "source.backup"
    assert pg("pg_dump", "-Fc", "--dbname", name, "-f", str(dump)).returncode == 0
    yield dump
    pg("dropdb", "--if-exists", "--maintenance-db=postgres", name)


@real
def test_a_real_backup_is_restored_verified_and_dropped(source_dump):
    before = orphans()
    r = rehearse_postgres_restore(source_dump, database_url=PG_URL)
    assert r["status"] == "passed" and r["verified"] is True and r["cleanup_completed"] is True
    v = r["verification"]
    assert v["tables_expected"] == 3 and v["tables_restored"] == 3 and v["missing_tables"] == [] and v["empty_data_table_count"] == 1 and v["empty_data_tables"] == ["public.tab_empty"]
    assert r["recovery_seconds"] > 0 and r["restore_duration_seconds"] > 0 and r["recovery_seconds"] >= r["restore_duration_seconds"]
    assert orphans() == before                                                                 # no scratch database left behind


@real
def test_a_damaged_real_backup_fails_leaves_nothing_behind_and_is_recorded(source_dump, tmp_path):
    before = orphans()
    data = source_dump.read_bytes()
    source_dump.write_bytes(data[: len(data) // 2])                                            # cut the dump in half
    with pytest.raises(RecoveryRehearsalError) as e:
        rehearse_postgres_restore(source_dump, database_url=PG_URL)
    assert e.value.result["status"] == "failed" and e.value.result["error"] and orphans() == before
    record_rehearsal(tmp_path, e.value.result)
    assert recovery_assurance_report(tmp_path)["assurance"] == "none"                          # a failure is on record; and with no pass, there is no assurance


@real
def test_wrong_credentials_fail_cleanly_without_a_traceback(source_dump):
    bad = PG_URL.replace("postgres:", "postgres_nobody:", 1) if "postgres:" in PG_URL else PG_URL
    with pytest.raises(RecoveryRehearsalError) as e:
        rehearse_postgres_restore(source_dump, database_url=bad)
    assert e.value.result["status"] == "failed" and orphans() == orphans()


@real
def test_a_real_timeout_still_cleans_up(source_dump):
    before = orphans()
    with pytest.raises(RecoveryRehearsalError, match="timed out") as e:
        rehearse_postgres_restore(source_dump, database_url=PG_URL, timeout=0)                  # every command is killed instantly
    assert e.value.result["status"] == "failed"
    assert orphans() == before


@real
def test_the_command_records_failures_and_reports_them(tmp_path, source_dump):
    """End to end through the real `velora ops` command: a rehearsal passes, a later one fails, and the report says FAILING (the old command recorded only successes)."""
    from velora.workspace import Workspace
    ws = Workspace.create(tmp_path / "ws")
    root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(root), "VELORA_POSTGRES_REHEARSAL_URL": PG_URL}
    env.pop("VELORA_WORKSPACE", None)

    def cli(*a):
        r = subprocess.run([__import__("sys").executable, "-m", "velora.cli", "--workspace", str(ws.root), "ops", *a], capture_output=True, text=True, env=env, timeout=240)
        return r.returncode, r.stdout, r.stderr
    assert cli("postgres-rehearse", str(source_dump))[0] == 0
    assert json.loads(cli("recovery-assurance")[1])["assurance"] == "current"
    broken = tmp_path / "broken.backup"; broken.write_bytes(b"this is not a dump")
    code, out, _ = cli("postgres-rehearse", str(broken))
    assert code == 1 and "not a readable pg_restore archive" in out
    rep = json.loads(cli("recovery-assurance")[1])
    assert rep["assurance"] == "failing" and rep["rehearsals_total"] == 2 and rep["rehearsals_passed"] == 1 and rep["consecutive_failures"] == 1
