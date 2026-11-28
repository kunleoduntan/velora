"""PostgreSQL-only database objects that apps ship with their code.

An app declares them in hooks.py:

    pg_objects = [{
        "name": "gl_entry_append_only",                       # unique; its checksum decides when to re-apply
        "description": "...",
        "requires": ["btree_gist"],                           # extensions it needs (optional); skipped, not failed, if they cannot be created
        "sql": ["CREATE OR REPLACE FUNCTION ...", "DROP TRIGGER IF EXISTS ...", "CREATE TRIGGER ..."],   # a LIST of statements; must be idempotent
    }]

They are applied inside `migrate` (so install, upgrade and `velora migrate` all do it), in the same transaction as the table changes (PostgreSQL DDL is
transactional: all or nothing), and only when the SQL text changed. On SQLite or any other database they do nothing - the Python code still enforces every rule;
these make the DATABASE enforce it too, so not even a raw SQL statement or a buggy script can break it.
"""
from __future__ import annotations

import hashlib

from sqlalchemy import insert, select, update

from .db.system import pg_object
from .document.document import now
from .exceptions import MetaError
from .meta.registry import registry

TRUSTED = {"pg_trgm", "unaccent", "btree_gist", "citext", "pgcrypto", "hstore", "tablefunc", "pg_stat_statements"}


def checksum(obj: dict) -> str:
    sql = obj["sql"] if isinstance(obj["sql"], list) else [obj["sql"]]
    return hashlib.sha256("\n;\n".join(sql).encode()).hexdigest()


def validate(objs: list[dict]) -> None:
    seen = set()
    for o in objs:
        if not o.get("name") or not o.get("sql"):
            raise MetaError(f"A pg_object needs a name and sql: {o!r}")
        if o["name"] in seen:
            raise MetaError(f"pg_object {o['name']!r} is declared twice")
        seen.add(o["name"])
        bad = [e for e in o.get("requires", []) if e not in TRUSTED]
        if bad:
            raise MetaError(f"pg_object {o['name']}: unknown extension(s) {bad}; allowed: {sorted(TRUSTED)}")


def ensure_extension(conn, name: str) -> bool:
    """CREATE EXTENSION if allowed; False (never an exception) when the server or the role does not permit it (managed hosts often restrict this)."""
    if name not in TRUSTED:
        raise MetaError(f"Extension {name!r} is not on the allowed list")
    try:
        with conn.begin_nested():
            conn.exec_driver_sql(f'CREATE EXTENSION IF NOT EXISTS "{name}"')
        return True
    except Exception:  # noqa: BLE001 - no privilege / not installed on the server
        return False


def apply(conn, dry_run: bool = False) -> list[str]:
    if conn.dialect.name != "postgresql":
        return []
    objs = registry.pg_objects()
    if not objs:
        return []
    validate(objs)
    t = pg_object
    have = {r["name"]: r["checksum"] for r in conn.execute(select(t.c.name, t.c.checksum)).mappings()}
    plan: list[str] = []
    for o in objs:
        cs = checksum(o)
        if have.get(o["name"]) == cs:
            continue
        missing = [e for e in o.get("requires", []) if dry_run or not ensure_extension(conn, e)]
        if missing and not dry_run:
            plan.append(f"SKIPPED PG OBJECT {o['name']}: extension {', '.join(missing)} is not available on this server (it will be retried on the next migrate)")
            continue
        plan.append(f"{'CHANGE' if o['name'] in have else 'APPLY'} PG OBJECT {o['name']}")
        if dry_run:
            continue
        try:
            with conn.begin_nested():
                for stmt in (o["sql"] if isinstance(o["sql"], list) else [o["sql"]]):
                    conn.exec_driver_sql(stmt.replace("%", "%%"))                   # psycopg treats a lone % as a placeholder; %% reaches the server as %
        except Exception as e:  # noqa: BLE001
            raise MetaError(f"PG object {o['name']} ({o['app']}) failed: {str(e).splitlines()[0]}") from None
        if o["name"] in have:
            conn.execute(update(t).where(t.c.name == o["name"]).values(checksum=cs, app=o["app"], applied_on=now()))
        else:
            conn.execute(insert(t).values(name=o["name"], app=o["app"], checksum=cs, applied_on=now()))
    return plan
