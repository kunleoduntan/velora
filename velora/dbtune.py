"""One-click database tuning. It changes how the database finds data, never the data itself.

What it does, in order:
  1. creates the indexes the DocType definitions call for that an older database may be missing (links, unique fields, `modified`);
  2. adds indexes for the columns people filter and sort by (standard-filter fields, dates, status fields, `docstatus`);
  3. on PostgreSQL, adds trigram indexes so the list and link search ("contains") stays fast on large tables;
  4. refreshes the planner's statistics (ANALYZE);
  5. reclaims space (VACUUM).
Every step is `IF NOT EXISTS` or read-only for the rows. Nothing is deleted, rewritten or moved.
"""
from __future__ import annotations

import re
import time

from sqlalchemy import Index, text

from . import db
from .db.tables import get_table, safe_identifier
from .exceptions import PermissionDenied
from .meta.registry import registry
from .permissions import get_session

FILTER_TYPES = {"Select", "Date", "Datetime", "Link", "Check"}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_admin() -> None:
    s = get_session()
    if s.user != "Administrator" and "System Manager" not in set(s.roles):
        raise PermissionDenied("Only a System Manager can tune the database.")


def _wanted_columns(meta) -> list[str]:
    """Columns worth an index beyond what the table already declares."""
    cols = ["docstatus"] if meta.is_submittable and not meta.istable else []
    for f in meta.value_fields:
        if f.unique or f.fieldtype == "Link":
            continue                                                       # already indexed by the table definition
        if f.in_standard_filter and f.fieldtype in FILTER_TYPES:
            cols.append(f.fieldname)
        elif f.fieldtype in ("Date", "Datetime") and (f.in_list_view or f.required):
            cols.append(f.fieldname)
        elif f.fieldname in ("status", "posting_date", "transaction_date", "approval_status", "workflow_state") and f.fieldtype in FILTER_TYPES | {"Data"}:
            cols.append(f.fieldname)
    return list(dict.fromkeys(cols))


def _size(conn) -> int:
    if conn.dialect.name == "postgresql":
        return int(conn.execute(text("select pg_database_size(current_database())")).scalar() or 0)
    if conn.dialect.name == "sqlite":
        return int(conn.exec_driver_sql("PRAGMA page_count").scalar() or 0) * int(conn.exec_driver_sql("PRAGMA page_size").scalar() or 0)
    return 0


def plan(conn) -> list[tuple[str, str, Index]]:
    """[(kind, table, Index)] still to be created. `kind` is 'declared' or 'filter'."""
    todo: list[tuple[str, str, Index]] = []
    insp_names: dict[str, set[str]] = {}
    from sqlalchemy import inspect
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())

    def have(table: str) -> set[str]:
        if table not in insp_names:
            insp_names[table] = {i["name"] for i in inspector.get_indexes(table)} if table in existing_tables else set()
        return insp_names[table]

    for meta in sorted(registry.all(), key=lambda m: m.name):
        try:
            table = get_table(meta.name)
        except Exception:                                                  # a doctype with no table of its own (virtual)
            continue
        if table.name not in existing_tables:
            continue
        for ix in table.indexes:
            if ix.name not in have(table.name):
                todo.append(("declared", table.name, ix))
        for col in _wanted_columns(meta):
            name = safe_identifier(f"tune_{table.name}_{col}")
            if col in table.c and name not in have(table.name):
                todo.append(("filter", table.name, Index(name, table.c[col])))
    return todo


def preview() -> dict:
    """What tuning would do, without doing it."""
    _require_admin()
    with db.get_engine().connect() as conn:
        todo = plan(conn)
        return {"database": conn.dialect.name, "size_bytes": _size(conn), "indexes_to_create": [f"{t}.{ix.name}" for _k, t, ix in todo]}


def tune(*, vacuum: bool = True) -> dict:
    """Run every step. Safe to repeat; a second run finds nothing to create."""
    _require_admin()
    started = time.monotonic()
    engine = db.get_engine()
    created: list[str] = []
    notes: list[str] = []
    with engine.begin() as conn:
        before = _size(conn)
        for _kind, _table, ix in plan(conn):
            try:
                ix.create(conn, checkfirst=True)
                created.append(f"{_table}.{ix.name}")
            except Exception as exc:                                       # one table failing must not stop the rest
                notes.append(f"Skipped {ix.name}: {str(exc).splitlines()[0][:120]}")
        if conn.dialect.name == "postgresql":
            created += _trigram_indexes(conn, notes)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        if conn.dialect.name == "postgresql":
            conn.exec_driver_sql("ANALYZE")
        elif conn.dialect.name == "sqlite":
            conn.exec_driver_sql("ANALYZE")
            conn.exec_driver_sql("PRAGMA optimize")
        if vacuum:
            try:
                conn.exec_driver_sql("VACUUM")
            except Exception as exc:                                       # e.g. another session holds a lock: statistics are still refreshed
                notes.append(f"Space was not reclaimed: {str(exc).splitlines()[0][:120]}")
        after = _size(conn)
    return {"database": engine.dialect.name, "indexes_created": created, "statistics_refreshed": True, "vacuumed": vacuum and not any(n.startswith("Space") for n in notes),
            "size_before": before, "size_after": after, "seconds": round(time.monotonic() - started, 2), "notes": notes}


def _trigram_indexes(conn, notes: list[str]) -> list[str]:
    """Trigram indexes make `contains` searches use an index. Needs the pg_trgm extension, which a managed database may not allow."""
    try:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except Exception:
        notes.append("Search indexes were not added: the pg_trgm extension is not allowed for this database user.")
        return []
    made = []
    for meta in registry.all():
        if meta.istable or not meta.title_field or not _IDENT.match(meta.title_field):
            continue
        try:
            table = get_table(meta.name).name
        except Exception:
            continue
        for col in ("name", meta.title_field):
            ix = safe_identifier(f"trgm_{table}_{col}")
            if conn.exec_driver_sql("select 1 from pg_indexes where indexname = %s", (ix,)).first():
                continue
            try:
                conn.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS "{ix}" ON "{table}" USING gin ("{col}" gin_trgm_ops)')
                made.append(f"{table}.{ix}")
            except Exception:
                continue
    return made
