"""Non-destructive PostgreSQL restore rehearsals, and the recovery evidence they produce.

A rehearsal restores a real backup into a disposable database, CHECKS that what came back matches what the archive says it holds, and drops the database again. What it
measures is how long recovery takes ON THIS MACHINE (create + restore + verify). It does not measure the time to notice a failure, decide, or repoint users, and it says
nothing about how much data a failure would lose (the RPO): that needs the backup's transaction watermark, which is not inferred here.

The evidence log keeps FAILED rehearsals as well as passed ones. A log of successes only cannot reveal that last night's rehearsal failed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

STALE_AFTER_DAYS = 35                      # a rehearsal older than this no longer says anything about today's backups
MAX_DATA_CHECKS = 200
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_$]+$")


class RecoveryRehearsalError(RuntimeError):
    """The rehearsal failed. `.result` holds the evidence record when a rehearsal actually ran (record it); it is None for setup problems such as a missing utility."""

    def __init__(self, message: str, result: dict | None = None):
        super().__init__(message)
        self.result = result


class _Finished:
    """Stands in for a command that could not run to completion (timed out, or the program could not start)."""

    def __init__(self, returncode: int, stderr: str):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ""


def _pg_environment(database_url: str | None = None) -> dict:
    # Child programs get what they need and NOT the framework's own secrets (VELORA_MASTER_KEY, VELORA_BACKUP_PASSWORD ...).
    env = {k: v for k, v in os.environ.items() if not k.startswith("VELORA_")}
    if database_url:
        parsed = urlsplit(database_url)
        if parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg"} or not parsed.hostname:
            raise RecoveryRehearsalError("A PostgreSQL connection URL is required")
        env["PGHOST"] = parsed.hostname
        if parsed.port:
            env["PGPORT"] = str(parsed.port)
        if parsed.username:
            env["PGUSER"] = unquote(parsed.username)
        if parsed.password:
            env["PGPASSWORD"] = unquote(parsed.password)
        if parsed.path and parsed.path.strip("/"):
            env["PGDATABASE"] = parsed.path.strip("/")
        query = dict(part.split("=", 1) for part in parsed.query.split("&") if "=" in part)
        if query.get("sslmode"):
            env["PGSSLMODE"] = query["sslmode"]
    return env


def _run(runner, args: list, env: dict, timeout: int):
    try:
        return runner(args, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return _Finished(124, f"timed out after {timeout} seconds")
    except OSError as exc:
        return _Finished(127, str(exc))


def expected_from_listing(listing: str) -> tuple[set, set]:
    """(tables, tables_with_data) the archive says it contains, from `pg_restore --list`: {(schema, name)}. Names that are not plain identifiers are skipped."""
    tables, data = set(), set()
    for line in (listing or "").splitlines():
        m = re.match(r"^\d+;\s+\d+\s+\d+\s+(TABLE DATA|TABLE)\s+(\S+)\s+(\S+)\s", line + " ")
        if not m or not _SAFE_NAME.match(m.group(2)) or not _SAFE_NAME.match(m.group(3)):
            continue
        (data if m.group(1) == "TABLE DATA" else tables).add((m.group(2), m.group(3)))
    return tables | data, data


def _verify(runner, env, scratch, tables: set, data_tables: set, timeout: int) -> dict:
    """Ask the restored database what it holds, and compare with what the archive promised."""
    sql = ("SELECT 'T', table_schema, table_name, '' FROM information_schema.tables "
           "WHERE table_type = 'BASE TABLE' AND table_schema NOT IN ('pg_catalog', 'information_schema')")
    checked = sorted(data_tables)[:MAX_DATA_CHECKS]
    for schema, name in checked:
        sql += f" UNION ALL SELECT 'D', '{schema}', '{name}', CASE WHEN EXISTS (SELECT 1 FROM \"{schema}\".\"{name}\") THEN 'rows' ELSE 'empty' END"
    out = _run(runner, ["psql", "--no-psqlrc", "-X", "-At", "-F", "|", "-v", "ON_ERROR_STOP=1", "--dbname", scratch, "-c", sql], env, timeout)
    if out.returncode != 0:
        return {"ok": False, "error": "Could not inspect the restored database: " + (out.stderr or "unknown error")[:500]}
    present, empty = set(), []
    for line in (out.stdout or "").splitlines():
        parts = line.split("|")
        if len(parts) == 4 and parts[0] == "T":
            present.add((parts[1], parts[2]))
        elif len(parts) == 4 and parts[0] == "D" and parts[3] == "empty":
            empty.append(f"{parts[1]}.{parts[2]}")
    missing = sorted(f"{s}.{n}" for s, n in tables - present)
    return {"ok": not missing, "tables_expected": len(tables), "tables_restored": len(tables & present), "missing_tables": missing[:20],
            "data_tables_checked": len(checked), "empty_data_tables": sorted(empty)[:20], "empty_data_table_count": len(empty),
            **({"error": f"{len(missing)} table(s) in the archive are missing after the restore"} if missing else {})}


def rehearse_postgres_restore(backup_path: str | Path, *, database_url: str | None = None, runner=subprocess.run, timeout: int = 900) -> dict:
    """Restore a custom/tar pg_dump into a unique disposable database, verify it against the archive, then drop it.

    Returns the evidence record on success. On failure raises RecoveryRehearsalError whose `.result` is the (failed) evidence record to keep."""
    backup = Path(backup_path).expanduser().resolve()
    if not backup.is_file():
        raise RecoveryRehearsalError(f"Backup file not found: {backup}")
    for command in ("pg_restore", "createdb", "dropdb"):
        if not shutil.which(command):
            raise RecoveryRehearsalError(f"Required PostgreSQL utility not found: {command}")
    env = _pg_environment(database_url or os.environ.get("VELORA_POSTGRES_REHEARSAL_URL"))
    stat = backup.stat()
    tested_at = datetime.now(timezone.utc)
    result = {"kind": "postgresql_restore_rehearsal", "backup": str(backup), "backup_bytes": stat.st_size,
              "backup_age_hours": round((tested_at.timestamp() - stat.st_mtime) / 3600, 2), "tested_at": tested_at.isoformat(),
              "status": "failed", "verified": False, "cleanup_completed": False}

    def fail(message: str):
        result["error"] = message
        raise RecoveryRehearsalError(json.dumps(result), result)

    listing = _run(runner, ["pg_restore", "--list", str(backup)], env, timeout)
    if listing.returncode != 0:
        fail("Backup is not a readable pg_restore archive: " + (listing.stderr or "unknown error")[:1000])
    tables, data_tables = expected_from_listing(getattr(listing, "stdout", "") or "")
    if not tables:
        fail("The archive lists no tables at all: it cannot be a backup of a Velora database")

    scratch = "velora_rehearsal_" + uuid.uuid4().hex[:16]
    result["scratch_database"] = scratch
    created, error, timings = False, None, {}
    try:
        created = True                                  # from here on the database MAY exist (a timeout kills the client, not the server's CREATE DATABASE), so cleanup always runs
        t = time.monotonic()
        create = _run(runner, ["createdb", "--maintenance-db=postgres", "--template=template0", scratch], env, timeout)
        timings["createdb_seconds"] = round(time.monotonic() - t, 3)
        if create.returncode != 0:
            raise RecoveryRehearsalError("Could not create disposable rehearsal database: " + (create.stderr or "unknown error")[:1000])
        t = time.monotonic()
        restored = _run(runner, ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "--dbname", scratch, str(backup)], env, timeout)
        timings["restore_duration_seconds"] = round(time.monotonic() - t, 3)         # the restore ALONE
        if restored.returncode != 0:
            raise RecoveryRehearsalError("PostgreSQL restore rehearsal failed: " + (restored.stderr or "unknown error")[:1000])
        if shutil.which("psql"):
            t = time.monotonic()
            result["verification"] = verification = _verify(runner, env, scratch, tables, data_tables, timeout)
            timings["verify_seconds"] = round(time.monotonic() - t, 3)
            if not verification["ok"]:
                raise RecoveryRehearsalError(verification.get("error", "The restored database does not match the archive"))
            result["verified"] = True
        else:
            result["verification"] = {"ok": None, "note": "psql is not installed, so the restored database was not inspected: this rehearsal proves the restore ran, not what it produced"}
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    finally:
        if created:
            dropped = _run(runner, ["dropdb", "--if-exists", "--maintenance-db=postgres", scratch], env, timeout)      # ALWAYS, even after a failure or a timeout
            if dropped.returncode != 0:
                result["cleanup_error"] = (dropped.stderr or "Could not drop rehearsal database")[:1000]
    result.update(timings)
    result["recovery_seconds"] = round(sum(timings.get(k, 0) for k in ("createdb_seconds", "restore_duration_seconds", "verify_seconds")), 3)
    result["cleanup_completed"] = created and "cleanup_error" not in result
    if error:
        fail(error)
    if "cleanup_error" in result:
        fail("The rehearsal database could not be dropped and must be removed by hand: " + scratch)
    result["status"] = "passed"
    return result


def record_rehearsal(workspace_root: str | Path, result: dict) -> Path:
    path = Path(workspace_root) / "logs" / "recovery-rehearsals.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")
    return path


def _when(record: dict) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(record.get("tested_at")))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recovery_assurance_report(workspace_root: str | Path, *, now: datetime | None = None, stale_after_days: int = STALE_AFTER_DAYS) -> dict:
    """What the rehearsals say about recovery TODAY: how many passed, whether the latest failed, how old the last pass is, and a worst-case (not a best-case) recovery time."""
    now = now or datetime.now(timezone.utc)
    path = Path(workspace_root) / "logs" / "recovery-rehearsals.jsonl"
    records, corrupt = [], 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                corrupt += 1
    passed = [r for r in records if r.get("status") == "passed"]
    latest, last_pass = (records[-1] if records else None), (passed[-1] if passed else None)
    trailing_failures = 0
    for r in reversed(records):
        if r.get("status") == "passed":
            break
        trailing_failures += 1
    when = _when(last_pass) if last_pass else None
    days_since = round((now - when).total_seconds() / 86400, 2) if when else None
    recent = [r.get("recovery_seconds", r.get("restore_duration_seconds")) for r in passed[-5:]]
    recent = [x for x in recent if isinstance(x, (int, float))]
    if not passed:
        assurance = "none"
    elif latest.get("status") != "passed":
        assurance = "failing"
    elif days_since is None or days_since > stale_after_days:
        assurance = "stale"
    elif "verified" in last_pass and not last_pass["verified"]:
        assurance = "unverified"
    else:
        assurance = "current"
    return {"assurance": assurance, "rehearsals_total": len(records), "rehearsals_passed": len(passed), "rehearsals_verified": sum(1 for r in passed if r.get("verified")),
            "consecutive_failures": trailing_failures, "days_since_last_pass": days_since, "stale": assurance in ("none", "stale"), "stale_after_days": stale_after_days,
            "latest_rehearsal": latest, "latest_restore_duration_seconds": last_pass.get("restore_duration_seconds") if last_pass else None,
            "measured_rto_seconds": max(recent) if recent else None,
            "median_recovery_seconds": round(statistics.median(recent), 3) if recent else None,
            "rto_basis": f"slowest of the last {len(recent)} passed rehearsal(s): create + restore + verify on this machine" if recent else None,
            "corrupt_log_lines": corrupt,
            "rpo_measurement": "Requires backup timestamp and source transaction watermark; not inferred from restore duration"}
