"""Backup and (atomic) restore of one database: SQLite file copy, or PostgreSQL through pg_dump / psql."""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..workspace import WorkspaceError


def _need(tool: str):
    if not shutil.which(tool):
        raise WorkspaceError(f"{tool} was not found. Install the PostgreSQL client tools (e.g. `apt install postgresql-client`).")


def verify_backup(path: Path) -> None:
    """Cheap sanity check before we trust a backup (readable gzip, not empty)."""
    try:
        with gzip.open(path, "rb") as fh:
            head = fh.read(64)
    except (OSError, EOFError) as e:
        raise WorkspaceError(f"Backup {path.name} is unreadable: {e}") from e
    if not head:
        raise WorkspaceError(f"Backup {path.name} is empty")


def restore_database(cfg: dict, sqlite_file: Path | None, backup: Path) -> None:
    """Replace the database's contents with the backup. PostgreSQL: one transaction (a failed restore changes nothing).
    SQLite: the backup is verified first, the old file is kept as *.pre-restore, then swapped in atomically."""
    verify_backup(backup)
    if cfg.get("db_type", "sqlite") == "sqlite":
        _restore_sqlite(sqlite_file, backup)
    else:
        _restore_pg(cfg, backup)


def _restore_sqlite(target: Path, backup: Path) -> None:
    """Restore IN PLACE through SQLite's backup API, never by swapping the file: a running server's pooled connections keep the
    old file open, and would go on reading stale data after a swap. The previous contents are kept as *.pre-restore."""
    if target is None:
        raise WorkspaceError("No SQLite file to restore into")
    tmp = Path(tempfile.mkstemp(dir=target.parent, suffix=".restoring")[1])
    try:
        with gzip.open(backup, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        try:
            src = sqlite3.connect(tmp)
            ok = src.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            tables = src.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
        except sqlite3.DatabaseError as e:
            raise WorkspaceError(f"The backup is not a valid database ({e}); nothing was changed") from e
        if not ok or tables == 0:
            src.close()
            raise WorkspaceError("The backup is not a valid database; nothing was changed")
        if target.exists():
            shutil.copy2(target, target.with_name(target.name + ".pre-restore"))
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    finally:
        tmp.unlink(missing_ok=True)


def _restore_pg(cfg: dict, backup: Path) -> None:
    _need("psql")
    fd, script = tempfile.mkstemp(suffix=".sql")
    try:
        with os.fdopen(fd, "wb") as out, gzip.open(backup, "rb") as dump:
            out.write(b"BEGIN;\nDROP OWNED BY CURRENT_USER CASCADE;\nCREATE SCHEMA IF NOT EXISTS public;\n")
            shutil.copyfileobj(dump, out)
            out.write(b"\nCOMMIT;\n")
        env = {**os.environ, "PGPASSWORD": cfg.get("db_password", "")}
        cmd = ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", cfg.get("db_host", "localhost"), "-p", str(cfg.get("db_port", 5432)),
               "-U", cfg["db_user"], "-d", cfg["db_name"], "-f", script]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode:                                  # the open transaction is rolled back when psql exits: nothing changed
            raise WorkspaceError(f"Restore failed and was rolled back (the database is unchanged): {proc.stderr.strip()[:300]}")
    finally:
        os.remove(script)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
