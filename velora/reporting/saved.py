"""Saved reports: a report-builder definition with a name, owned by one person, optionally shared company-wide.

Security model: only the DEFINITION is stored. Running a saved report re-checks the CURRENT user's permissions (read on the
DocType, and export for Excel), so sharing a report never shares data. Only the owner or a System Manager may edit or delete it,
and only a System Manager may share one.
"""
from __future__ import annotations

import json
import re
import secrets

from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from .. import db
from ..db.system import saved_report
from ..document.document import now
from ..exceptions import DoesNotExistError, PermissionDenied, ValidationError
from ..meta.registry import registry
from ..permissions import get_session, has_permission
from .runner import SPEC_KEYS, prepare_adhoc, run_adhoc
from .service import export_adhoc

MAX_SPEC_BYTES = 20_000
_RID = re.compile(r"^SR-[0-9a-f]{8}$")


def _is_manager() -> bool:
    s = get_session()
    return s.user == "Administrator" or "System Manager" in s.roles


def _clean_name(name) -> str:
    name = str(name or "").strip()
    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise ValidationError("Give the report a name of 1-100 characters")
    return name


def _clean_spec(spec) -> dict:
    if not isinstance(spec, dict):
        raise ValidationError("A report definition must be an object")
    if len(json.dumps(spec, default=str)) > MAX_SPEC_BYTES:
        raise ValidationError("Report definition is too large")
    prepare_adhoc(spec)                                            # refuse an invalid or forbidden definition NOW, not when someone runs it
    return {k: v for k, v in spec.items() if k in SPEC_KEYS}



# Immutable saved-report revisions. A restore publishes a new revision rather than rewriting history.
md = MetaData()
_revision = Table("vl_saved_report_revision", md,
    Column("id", String(32), primary_key=True), Column("report_id", String(20), nullable=False, index=True),
    Column("version", Integer, nullable=False), Column("name", String(100), nullable=False),
    Column("spec", JSON, nullable=False), Column("shared", Integer, nullable=False, default=0),
    Column("author", String(254)), Column("created_on", DateTime))

def _ensure_revisions():
    from ..db.extra_tables import ensure
    ensure(md)

def _snapshot(rid: str):
    _ensure_revisions()
    with db.transaction() as conn:
        current = conn.execute(select(saved_report).where(saved_report.c.id == rid)).mappings().first()
        if not current: raise DoesNotExistError("Saved report not found")
        version = (conn.execute(select(_revision.c.version).where(_revision.c.report_id == rid).order_by(_revision.c.version.desc())).scalar() or 0) + 1
        row = dict(id=secrets.token_hex(16), report_id=rid, version=version, name=current["name"], spec=current["spec"],
                   shared=1 if current["shared"] else 0, author=get_session().user, created_on=now())
        conn.execute(insert(_revision).values(**row))
    return row

def list_versions(rid: str) -> list[dict]:
    cur = get_saved(rid)
    if not cur["can_edit"]: raise PermissionDenied("Only the owner or a System Manager can inspect report revisions")
    _ensure_revisions()
    with db.transaction() as conn:
        rows = conn.execute(select(_revision).where(_revision.c.report_id == rid).order_by(_revision.c.version.desc())).mappings().all()
    return [dict(x) for x in rows]

def restore_version(rid: str, version: int) -> dict:
    cur = get_saved(rid)
    if not cur["can_edit"]: raise PermissionDenied("Only the owner or a System Manager can restore report revisions")
    _ensure_revisions()
    with db.transaction() as conn:
        row = conn.execute(select(_revision).where(_revision.c.report_id == rid, _revision.c.version == int(version))).mappings().first()
    if not row: raise DoesNotExistError("Saved report revision not found")
    return update_saved(rid, name=row["name"], spec=row["spec"], shared=bool(row["shared"]))

def _row(r) -> dict:
    return {"id": r["id"], "name": r["name"], "doctype": r["doctype"], "owner": r["owner"], "shared": bool(r["shared"]), "spec": r["spec"],
            "can_edit": r["owner"] == get_session().user or _is_manager(), "updated_on": r["updated_on"].isoformat() if r["updated_on"] else None}


def _visible(r) -> bool:
    return r["owner"] == get_session().user or bool(r["shared"])


def get_saved(rid: str) -> dict:
    if not _RID.match(rid or ""):                                     # also keeps NUL bytes etc. away from the database (PostgreSQL rejects them)
        raise DoesNotExistError("Saved report not found")
    with db.transaction() as conn:
        r = conn.execute(select(saved_report).where(saved_report.c.id == rid)).mappings().first()
    if r is None or not _visible(r):
        raise DoesNotExistError("Saved report not found")           # same answer whether it does not exist or is someone else's private report
    return _row(r)


def list_saved() -> list[dict]:
    with db.transaction() as conn:
        rows = conn.execute(select(saved_report).order_by(saved_report.c.name)).mappings().all()
    out = []
    for r in rows:
        if _visible(r) and registry.exists(r["doctype"]) and has_permission(registry.get(r["doctype"]), "read"):
            d = _row(r)
            d.pop("spec")
            out.append(d)
    return out


def create_saved(name, spec, shared: bool = False) -> dict:
    name, spec = _clean_name(name), _clean_spec(spec)
    if shared and not _is_manager():
        raise PermissionDenied("Only a System Manager can share a report with the company")
    rid = "SR-" + secrets.token_hex(4)
    try:
        with db.transaction() as conn:
            conn.execute(insert(saved_report).values(id=rid, name=name, owner=get_session().user, doctype=spec["doctype"], spec=spec,
                                                     shared=bool(shared), created_on=now(), updated_on=now()))
    except IntegrityError:
        raise ValidationError(f"You already have a saved report called {name!r}") from None
    _snapshot(rid)
    return get_saved(rid)


def update_saved(rid: str, name=None, spec=None, shared=None) -> dict:
    cur = get_saved(rid)
    if not cur["can_edit"]:
        raise PermissionDenied("Only the owner or a System Manager can change this report")
    vals: dict = {"updated_on": now()}
    if name is not None:
        vals["name"] = _clean_name(name)
    if spec is not None:
        vals["spec"] = _clean_spec(spec)
        vals["doctype"] = vals["spec"]["doctype"]
    if shared is not None:
        if bool(shared) != cur["shared"] and not _is_manager():
            raise PermissionDenied("Only a System Manager can share a report with the company")
        vals["shared"] = bool(shared)
    try:
        with db.transaction() as conn:
            conn.execute(update(saved_report).where(saved_report.c.id == rid).values(**vals))
    except IntegrityError:
        raise ValidationError("You already have a saved report with that name") from None
    _snapshot(rid)
    return get_saved(rid)


def delete_saved(rid: str) -> None:
    cur = get_saved(rid)
    if not cur["can_edit"]:
        raise PermissionDenied("Only the owner or a System Manager can delete this report")
    with db.transaction() as conn:
        conn.execute(delete(saved_report).where(saved_report.c.id == rid))


def run_saved(rid: str):
    spec = get_saved(rid)["spec"]
    result = run_adhoc(spec)
    return result


def export_saved(rid: str):
    return export_adhoc(get_saved(rid)["spec"])
