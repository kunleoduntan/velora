"""Builds SQLAlchemy Core `Table` objects from DocType metadata (no ORM)."""
from __future__ import annotations

import hashlib
import re

from sqlalchemy import Column, DateTime, Index, Integer, MetaData, SmallInteger, String, Table

from ..meta.spec import COLUMN_TYPES, DocType
from ..site import current

MAX_IDENT = 63  # PostgreSQL limit; stricter than Oracle (128) and SQLite, so names stay portable


def safe_identifier(raw: str, max_len: int = MAX_IDENT) -> str:
    """Deterministic, portable identifier: lowercase, [a-z0-9_], hash-truncated if too long."""
    ident = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    if len(ident) <= max_len:
        return ident
    digest = hashlib.sha1(ident.encode()).hexdigest()[:8]
    return f"{ident[: max_len - 9]}_{digest}"


def table_name(doctype: str) -> str:
    return safe_identifier("tab_" + doctype)


def build_table(meta: DocType, metadata: MetaData) -> Table:
    tname = table_name(meta.name)
    cols = [
        Column("name", String(255), primary_key=True),
        Column("owner", String(140)),
        Column("creation", DateTime),
        Column("modified", DateTime),
        Column("modified_by", String(140)),
        Column("docstatus", SmallInteger, default=0),
        Column("idx", Integer),
    ]
    if meta.istable:
        cols += [Column("parent", String(255)), Column("parenttype", String(140)), Column("parentfield", String(140))]
    for f in meta.value_fields:
        cols.append(Column(f.fieldname, COLUMN_TYPES[f.fieldtype](f), nullable=True))
    idx = []
    if meta.istable:
        idx.append(Index(safe_identifier(f"ix_{tname}_parent"), "parent"))
    else:
        idx.append(Index(safe_identifier(f"ix_{tname}_modified"), "modified"))
    for f in meta.value_fields:
        if f.unique:
            idx.append(Index(safe_identifier(f"uq_{tname}_{f.fieldname}"), f.fieldname, unique=True))
        elif f.fieldtype == "Link":
            idx.append(Index(safe_identifier(f"ix_{tname}_{f.fieldname}"), f.fieldname))
        elif f.fieldtype == "JSON" and f.json_index and current().engine.dialect.name == "postgresql":
            idx.append(Index(safe_identifier(f"gin_{tname}_{f.fieldname}"), f.fieldname, postgresql_using="gin", postgresql_ops={f.fieldname: "jsonb_path_ops"}))
    return Table(tname, metadata, *cols, *idx)


def get_table(doctype: str) -> Table:
    site = current()
    if doctype not in site.table_cache:
        site.table_cache[doctype] = build_table(site.registry.get(doctype), site.metadata)
    return site.table_cache[doctype]


def reset():
    current().reset_tables()
