"""Tables owned by framework engines that are not DocTypes (print formats, jobs, scripts, dashboards, files, workflows, the website, the portal, integrations).

They used to be created by each engine during a REQUEST (`create_all` in its own `ensure()`), so `velora upgrade`'s plan never showed them and an upgrade never added a new column to
them. They now belong to the migration: `schema.migrate()` creates and extends them exactly like the system tables, and `ensure()` below is only a safety net for a database that
has not been migrated yet (a library session, a test): it does nothing once a table is known to exist.
"""
from __future__ import annotations

import importlib
import weakref

from sqlalchemy import MetaData

# (module, name of its MetaData). Listed explicitly: a table is part of the framework only if someone decided so here.
OWNERS: tuple[tuple[str, str], ...] = (
    ("velora.printing", "md"), ("velora.jobs", "_meta"), ("velora.scripts", "md"), ("velora.dashboards", "md"), ("velora.integration_engine", "_meta"),
    ("velora.workflow_orchestration", "md"), ("velora.workflows", "md"), ("velora.files", "md"), ("velora.portal", "md"), ("velora.workflow_automation", "md"), ("velora.application_workspaces", "md"), ("velora.website", "md"), ("velora.reporting.saved", "md"), ("velora.reporting.layouts", "md"), ("velora.rules", "md"), ("velora.policy_governance", "md"), ("velora.settings_governance", "md"), ("velora.activity", "md"), ("velora.ai", "md"),
    ("velora.ai_tool_engine", "md"), ("velora.ai_migrations", "md"), ("velora.ai_developer", "md"), ("velora.ai_app_builder", "md"), ("velora.document.recycle_bin", "md"),
)
_ensured: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()          # engine -> {id(metadata)} known to exist (and committed)


def metadatas() -> list[MetaData]:
    return [getattr(importlib.import_module(mod), attr) for mod, attr in OWNERS]


def tables() -> list:
    """Every engine table, in dependency order within each owner."""
    return [t for md in metadatas() for t in md.sorted_tables]


def ensure(md: MetaData) -> None:
    """Create `md`'s tables if they are missing, once per engine. Inside a transaction the table is only remembered AFTER the commit: on PostgreSQL the DDL is part of the
    transaction, so a rollback would otherwise leave us believing a table exists that does not."""
    from .. import db
    try:
        bind, in_tx = db.conn(), True
    except RuntimeError:
        bind, in_tx = db.get_engine(), False
    engine = getattr(bind, "engine", bind)
    known = _ensured.setdefault(engine, set())
    if id(md) in known:
        return
    md.create_all(bind)                                       # checks first: only missing tables are created
    if in_tx:
        db.on_commit(lambda: known.add(id(md)))
    else:
        known.add(id(md))
