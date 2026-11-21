"""Schema sync ("migrate"): diff DocType metadata against the live database.

Policy:
  * create missing tables, add missing columns, create missing indexes
  * SAFE widening on PostgreSQL only: a longer VARCHAR, Integer -> BigInteger
  * NEVER drop columns/tables, shrink, or convert between kinds of data automatically: those are reported as WARNING lines
    (the app ships a data patch for them) - a lossy change is never applied silently
  * every step is reported; `dry_run=True` reports without executing
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, JSON, Numeric, String, inspect, types as sa_types

from .. import db
from ..meta.registry import registry
from . import tables
from .system import system_metadata


def _family(t) -> str:
    if isinstance(t, Boolean):
        return "bool"
    if isinstance(t, Integer):
        return "number"
    if isinstance(t, (Float, Numeric)):
        return "number"
    if isinstance(t, DateTime):
        return "datetime"
    if isinstance(t, Date):
        return "date"
    if isinstance(t, JSON):
        return "json"
    if isinstance(t, String) or isinstance(t, sa_types.Text):
        return "text"
    return "other"


def _compare_column(conn, table, col, actual, plan, dry_run):
    """Existing column vs what the DocType now says."""
    prep = conn.dialect.identifier_preparer
    want, have = col.type, actual["type"]
    fw, fh = _family(want), _family(have)
    pg = conn.dialect.name == "postgresql"
    alter = None
    if fw == "text" and fh == "text":
        wl, hl = getattr(want, "length", None), getattr(have, "length", None)
        if wl and hl and wl > hl:
            alter = f"VARCHAR({wl})"                                     # widening never loses data
    elif isinstance(want, BigInteger) and isinstance(have, Integer) and not isinstance(have, BigInteger):
        alter = "BIGINT"
    elif pg and fw == fh == "json" and want.compile(dialect=conn.dialect).upper() == "JSONB" and not isinstance(have, JSONB):
        alter = f"JSONB USING {prep.quote(col.name)}::jsonb"            # an older database stored plain json: convert once (rewrites the table; values are kept)
    elif fw != fh and "other" not in (fw, fh):
        plan.append(f"WARNING: {table.name}.{col.name} is {str(have).upper()} in the database but the DocType now says "
                    f"{want.compile(dialect=conn.dialect).upper()}: not changed automatically (ship a data patch)")
        return
    if alter and pg:
        sql = f"ALTER TABLE {prep.quote(table.name)} ALTER COLUMN {prep.quote(col.name)} TYPE {alter}"
        plan.append(sql)
        if not dry_run:
            conn.exec_driver_sql(sql)


def _sync_table(conn, table, plan, dry_run):
    insp = inspect(conn)
    if not insp.has_table(table.name):
        plan.append(f"CREATE TABLE {table.name}")
        if not dry_run:
            table.create(conn)
        return
    prep = conn.dialect.identifier_preparer
    reflected = {c["name"]: c for c in insp.get_columns(table.name)}
    existing_cols = set(reflected)
    for col in table.columns:
        if col.name in reflected and not col.primary_key:
            _compare_column(conn, table, col, reflected[col.name], plan, dry_run)
        if col.name not in existing_cols:
            ddl = col.type.compile(dialect=conn.dialect)
            sql = f"ALTER TABLE {prep.quote(table.name)} ADD COLUMN {prep.quote(col.name)} {ddl}"
            plan.append(sql)
            if not dry_run:
                conn.exec_driver_sql(sql)
    existing_ix = {i["name"] for i in insp.get_indexes(table.name)}
    for ix in table.indexes:
        if ix.name not in existing_ix:
            plan.append(f"CREATE INDEX {ix.name} ON {table.name}")
            if not dry_run:
                ix.create(conn)


def migrate(dry_run: bool = False) -> list[str]:
    """Bring the database in line with installed apps' metadata. Returns the plan."""
    plan: list[str] = []
    # PostgreSQL DDL is transactional: a failure part-way rolls the whole migrate back.
    with db.transaction() as conn:
        from .. import pg
        pg.require_supported(conn)                            # a PostgreSQL that is too old fails HERE, with the fix, before anything is touched
        for t in system_metadata.sorted_tables:
            _sync_table(conn, t, plan, dry_run)
        from . import extra_tables
        for t in extra_tables.tables():                       # print formats, jobs, scripts, dashboards, files, workflows, website, portal, integrations: planned, created and extended here
            _sync_table(conn, t, plan, dry_run)
        for meta in registry.all():
            _sync_table(conn, tables.get_table(meta.name), plan, dry_run)
        from .. import pgobjects
        plan += pgobjects.apply(conn, dry_run)                # PostgreSQL-only triggers/constraints/indexes the apps declare (a no-op elsewhere)
    return plan


def ensure_system_tables() -> list[str]:
    """Create the framework's own tables (idempotent). Needed before apps can be recorded as installed."""
    from . import extra_tables
    plan: list[str] = []
    with db.transaction() as conn:
        for t in system_metadata.sorted_tables:
            _sync_table(conn, t, plan, False)
        for t in extra_tables.tables():                       # a new company or site starts with every engine table too, not only after its first use
            _sync_table(conn, t, plan, False)
    return plan
