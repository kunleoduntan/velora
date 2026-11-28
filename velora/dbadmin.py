"""PostgreSQL administration helpers shared by site provisioning and company provisioning."""
from __future__ import annotations

import hashlib
import re

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from .workspace import WorkspaceError

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def pg_ident(seed: str, prefix: str = "_") -> str:
    return prefix + hashlib.sha1(seed.encode()).hexdigest()[:16]


def _safe_ident(name: str) -> str:
    if not _IDENT.match(name or ""):
        raise WorkspaceError(f"Invalid PostgreSQL identifier {name!r}: use lowercase letters, digits and underscores (max 63)")
    return name


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def root_engine(host, port, user, password):
    url = URL.create("postgresql+psycopg", username=user, password=password, host=host, port=int(port), database="postgres")
    return create_engine(url, isolation_level="AUTOCOMMIT")


def provision_pg(host, port, root_user, root_password, db_name, db_user, db_password):
    """Create a dedicated login role and an empty database it owns. Cleans up the role if anything fails."""
    _safe_ident(db_name), _safe_ident(db_user)
    root = root_engine(host, port, root_user, root_password)
    try:
        with root.connect() as c:
            c.exec_driver_sql(f'CREATE ROLE "{db_user}" LOGIN PASSWORD {_lit(db_password)}')
            try:
                c.exec_driver_sql(f'CREATE DATABASE "{db_name}" OWNER "{db_user}"')
            except Exception:
                c.exec_driver_sql(f'DROP ROLE IF EXISTS "{db_user}"')
                raise
    except Exception as e:  # noqa: BLE001
        raise WorkspaceError(f"Could not provision the database: {str(e).splitlines()[0]}") from e
    finally:
        root.dispose()


def drop_pg(host, port, root_user, root_password, db_name, db_user):
    _safe_ident(db_name), _safe_ident(db_user)
    root = root_engine(host, port, root_user, root_password)
    try:
        with root.connect() as c:
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
            c.exec_driver_sql(f'DROP ROLE IF EXISTS "{db_user}"')
    finally:
        root.dispose()


def check_connect(url: str):
    eng = create_engine(url)
    try:
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # noqa: BLE001
        raise WorkspaceError(f"Cannot connect to the database: {str(e).splitlines()[0]}") from e
    finally:
        eng.dispose()


def check_empty_database(url: str):
    """Reject an existing PostgreSQL database containing user tables before first Velora initialization."""
    from sqlalchemy import inspect
    eng = create_engine(url)
    try:
        with eng.connect() as conn:
            insp = inspect(conn)
            schemas = [s for s in insp.get_schema_names() if s not in ("pg_catalog", "information_schema")]
            tables, views = [], []
            for schema in schemas:
                tables.extend(f"{schema}.{name}" for name in insp.get_table_names(schema=schema))
                views.extend(f"{schema}.{name}" for name in insp.get_view_names(schema=schema))
            if tables or views:
                sample = ", ".join((tables + views)[:8])
                raise WorkspaceError(f"The selected PostgreSQL database is not empty (found: {sample}). Choose an empty database or use a documented migration process.")
    except WorkspaceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise WorkspaceError(f"Could not verify that the PostgreSQL database is empty: {str(e).splitlines()[0]}") from e
    finally:
        eng.dispose()
