"""What this PostgreSQL server offers and how well it is set up - for `velora pg status` and `velora doctor`."""
from __future__ import annotations

from sqlalchemy import text

from .pgobjects import TRUSTED, ensure_extension
from .meta.registry import registry

SETTINGS = ("server_version", "archive_mode", "wal_level", "shared_preload_libraries", "track_io_timing", "jit", "max_connections", "shared_buffers", "work_mem",
            "effective_cache_size", "synchronous_commit", "autovacuum")
RECOMMENDED = ("pg_trgm", "unaccent", "btree_gist", "pg_stat_statements")


def is_pg(conn) -> bool:
    return conn.dialect.name == "postgresql"


def _major(v: str) -> int:
    try:
        return int(v.split(".")[0].split()[0])
    except ValueError:
        return 0


def require_supported(conn) -> None:
    """Refuse, with the fix, a PostgreSQL server that is too old for Velora (no-op on other databases)."""
    if is_pg(conn):
        from . import compat
        compat.require_postgres(int(conn.exec_driver_sql("show server_version_num").scalar()))


WARN_CONNECTIONS = 70          # percent of the usable connections in use at which Velora starts to warn


def summarize_connections(rows, max_connections: int, reserved: int) -> dict:
    """rows: [(role, database, state, count)]. `usable` excludes the slots PostgreSQL keeps for superusers: when `in_use` reaches it, every ordinary connection is refused with
    'remaining connection slots are reserved for roles with the SUPERUSER attribute'."""
    usable = max(1, max_connections - reserved)
    total = sum(r[3] for r in rows)
    top = [{"role": r[0], "database": r[1], "state": r[2], "connections": r[3]} for r in sorted(rows, key=lambda r: -r[3])[:6]]
    return {"in_use": total, "max": max_connections, "reserved_for_superusers": reserved, "usable": usable, "percent": round(total * 100 / usable), "top": top}


def connection_advice(info: dict) -> str | None:
    if info["percent"] >= 100:
        return (f"PostgreSQL is OUT of connections ({info['in_use']} of {info['usable']} usable): new connections are refused until some close. See who holds them below; "
                "restart the program that holds the most idle ones, then raise max_connections or put pgbouncer in front.")
    if info["percent"] >= WARN_CONNECTIONS:
        return (f"{info['in_use']} of {info['usable']} usable PostgreSQL connections are in use ({info['percent']}%). Find the biggest holders with `velora pg status`; "
                "if it is not Velora, raise max_connections or use pgbouncer.")
    return None


def connections(conn) -> dict:
    """How many connections are in use, of how many, and who holds them (other roles' details are only visible to a role allowed to see them)."""
    max_c = int(conn.execute(text("show max_connections")).scalar())
    reserved = int(conn.execute(text("show superuser_reserved_connections")).scalar())
    rows = conn.execute(text("select coalesce(usename, '(hidden from this role)'), coalesce(datname, '-'), coalesce(state, '-'), count(*) from pg_stat_activity "
                             "where backend_type = 'client backend' group by 1, 2, 3")).all()
    return summarize_connections([tuple(r) for r in rows], max_c, reserved)


def status(conn) -> dict:
    if not is_pg(conn):
        return {"postgresql": False, "dialect": conn.dialect.name, "advice": ["This database is not PostgreSQL: the database-level integrity rules, "
                                                                            "advanced reports and other PostgreSQL features are off. Use PostgreSQL for production."]}
    q = lambda sql: conn.execute(text(sql)).all()  # noqa: E731
    st = {r[0]: r[1] for r in q("select name, setting from pg_settings where name = any(:n)".replace(":n", "array[" + ",".join(f"'{s}'" for s in SETTINGS) + "]"))}
    st["server_version"] = conn.execute(text("show server_version")).scalar()
    installed = {r[0] for r in q("select extname from pg_extension")}
    available = {r[0] for r in q("select name from pg_available_extensions")}
    # reltuples is -1 when a table has never been analysed: show that as unknown, not as a negative count
    tables = [{"table": r[0], "size": r[1], "rows_estimate": int(r[2]) if r[2] is not None and r[2] >= 0 else None} for r in q(
        "select c.relname, pg_size_pretty(pg_total_relation_size(c.oid)), c.reltuples from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind in ('r','p') order by pg_total_relation_size(c.oid) desc limit 8")]
    from .db.system import pg_object
    applied = [r[0] for r in conn.execute(pg_object.select().with_only_columns(pg_object.c.name)).all()]
    declared = [o["name"] for o in registry.pg_objects()]
    advice = []
    from . import compat
    pst, _pd, pfix = compat.postgres_status(int(conn.exec_driver_sql("show server_version_num").scalar()))
    if pst != "ok":
        advice.append(pfix)
    if st.get("archive_mode") == "off":
        advice.append("WAL archiving is OFF: you can restore a backup but NOT to a point in time. For production enable archive_mode and archive_command (or use pgBackRest / Barman / your host's PITR).")
    if "pg_stat_statements" not in st.get("shared_preload_libraries", ""):
        advice.append("pg_stat_statements is not preloaded: you cannot see which queries are slow. Add it to shared_preload_libraries and CREATE EXTENSION pg_stat_statements.")
    if st.get("autovacuum") == "off":
        advice.append("autovacuum is OFF: tables will bloat. Turn it on.")
    if st.get("synchronous_commit") == "off":
        advice.append("synchronous_commit is off: a crash can lose the last moments of committed work. Not for accounting.")
    missing = [e for e in RECOMMENDED if e not in installed and e in available and e != "pg_stat_statements"]
    if missing:
        advice.append(f"Recommended extensions not installed here: {', '.join(missing)}. `velora pg optimize` installs them when your role is allowed to.")
    conns = connections(conn)
    note = connection_advice(conns)
    if note:
        advice.insert(0, note)
    pending = [n for n in declared if n not in applied]
    if pending:
        advice.append(f"Database objects declared by your apps but not applied: {', '.join(pending)}. Run `velora migrate` (or `velora upgrade`).")
    return {"postgresql": True, "version": st["server_version"], "settings": st, "extensions": {"installed": sorted(installed), "available": sorted(available & TRUSTED)},
            "connections": conns, "largest_tables": tables, "objects": {"applied": applied, "declared": declared, "pending": pending}, "advice": advice}


def optimize(conn) -> dict:
    """Install the recommended extensions (where permitted), apply pending app objects' extensions, and refresh planner statistics."""
    if not is_pg(conn):
        return {"postgresql": False}
    got = {e: ensure_extension(conn, e) for e in ("pg_trgm", "unaccent", "btree_gist")}
    conn.exec_driver_sql("ANALYZE")
    return {"postgresql": True, "extensions": got, "analyzed": True}
