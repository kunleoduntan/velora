"""Which submitted documents stand in the way of cancelling a document, and cancelling them together.

The ERPNext rule, in Velora's words: a document cannot be cancelled while ANOTHER SUBMITTED document still points at it, unless that
document is one the cancelled document cleans up by itself (payments allocated to an invoice, ledger rows, reconciliation matches ...).

* Static links are found from the DocType metadata: every Link field, in the document or in one of its child tables, that points at it.
* Links an app keeps in plain fields (a `source_document` next to a `source_doctype`) are supplied by the app through the hook
  `linked_documents_provider` (a module with `dynamic_links(doctype, name) -> [(doctype, name), ...]`).
* A controller lists what it unlinks by itself in `ignore_linked_doctypes` (a tuple of DocType names), as ERPNext does.
* "Cancel all" walks the chain, cancels the last documents first and the chosen one last, in ONE transaction: any failure undoes all.
"""
from __future__ import annotations

import importlib

from sqlalchemy import select

from . import db
from .db.tables import get_table
from .exceptions import LinkedDocumentsError, PermissionDenied
from .meta.registry import registry

MAX_LISTED = 25


def _providers() -> list:
    out = []
    for app in registry._apps:
        try:
            hooks = importlib.import_module(f"{app}.hooks")
        except ModuleNotFoundError as exc:
            if exc.name == f"{app}.hooks":
                continue
            raise
        path = getattr(hooks, "linked_documents_provider", None)
        if path:
            out.append(importlib.import_module(path))
    return out


def _ignored(doctype: str, name: str | None = None) -> tuple:
    cls = registry.controller_for(doctype)
    return tuple(getattr(cls, "ignore_linked_doctypes", ()) or ())


def submitted_dependents(doctype: str, name: str) -> list[dict]:
    """Submitted documents that point at (doctype, name) and are not something it unlinks by itself."""
    ignore = set(_ignored(doctype))
    found: dict[tuple, dict] = {}
    with db.transaction() as c:
        for dt, f in registry.links_to(doctype):
            table = get_table(dt.name)
            if dt.istable:
                rows = c.execute(select(table.c.parent, table.c.parenttype).where(table.c[f.fieldname] == name)).all()
                refs = {(r[1], r[0]) for r in rows if r[1]}
            else:
                refs = {(dt.name, r[0]) for r in c.execute(select(table.c.name).where(table.c[f.fieldname] == name)).all()}
            for ref_dt, ref_name in refs:
                if ref_dt in ignore or (ref_dt, ref_name) == (doctype, name) or not registry.exists(ref_dt):
                    continue
                found[(ref_dt, ref_name)] = {"doctype": ref_dt, "name": ref_name, "via": f.label or f.fieldname}
    for provider in _providers():
        fn = getattr(provider, "dynamic_links", None)
        for ref_dt, ref_name in (fn(doctype, name) if callable(fn) else []):
            if ref_dt not in ignore and (ref_dt, ref_name) != (doctype, name) and registry.exists(ref_dt):
                found.setdefault((ref_dt, ref_name), {"doctype": ref_dt, "name": ref_name, "via": "source"})
    out = []
    with db.transaction() as c:
        for (ref_dt, ref_name), info in sorted(found.items()):
            if not registry.get(ref_dt).is_submittable:
                continue
            table = get_table(ref_dt)
            status = c.execute(select(table.c.docstatus).where(table.c.name == ref_name)).scalar()
            if status == 1:
                out.append(info)
    return out


def blocking_message(doctype: str, name: str, blockers: list[dict]) -> str:
    listed = ", ".join(f"{b['doctype']} {b['name']}" for b in blockers[:5]) + (f" and {len(blockers) - 5} more" if len(blockers) > 5 else "")
    return (f"Cannot cancel {doctype} {name}: it is used by submitted {listed}. Cancel those first, or use Cancel All to cancel them together.")


def check_can_cancel(doc) -> None:
    blockers = submitted_dependents(doc.doctype, doc.name)
    if blockers:
        raise LinkedDocumentsError(blocking_message(doc.doctype, doc.name, blockers), blockers)


def cancel_chain(doctype: str, name: str) -> list[dict]:
    """Everything that must be cancelled for (doctype, name) to be cancelled, in the order to cancel it (the chosen document last)."""
    order: list[dict] = []
    seen: set[tuple] = set()
    visiting: set[tuple] = set()

    def visit(dt: str, nm: str, via: str = ""):
        key = (dt, nm)
        if key in seen:
            return
        if key in visiting:                                    # a loop of documents pointing at each other: stop here, cancelling will report it
            return
        visiting.add(key)
        for b in submitted_dependents(dt, nm):
            visit(b["doctype"], b["name"], b.get("via", ""))
        visiting.discard(key)
        seen.add(key)
        order.append({"doctype": dt, "name": nm, "via": via})

    visit(doctype, name)
    return order


def preview(doctype: str, name: str) -> dict:
    chain = cancel_chain(doctype, name)
    return {"doctype": doctype, "name": name, "dependents": [c for c in chain if (c["doctype"], c["name"]) != (doctype, name)]}


def cancel_all(doctype: str, name: str, reason: str | None = None) -> list[dict]:
    """Cancel the document and every submitted document that depends on it, last-created chain first. All or nothing."""
    from .document import get_doc
    done = []
    with db.transaction():
        for item in cancel_chain(doctype, name):
            doc = get_doc(item["doctype"], item["name"])
            if int(doc.docstatus or 0) != 1:
                continue
            try:
                doc.cancel(reason=reason)
            except PermissionDenied as exc:
                raise PermissionDenied(f"You may not cancel {item['doctype']} {item['name']}, which depends on {doctype} {name}: {exc}") from exc
            done.append({"doctype": item["doctype"], "name": item["name"]})
    return done
