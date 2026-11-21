"""Correcting a submitted document the ERPNext way: CANCEL it, then AMEND it (a new draft copy linked to the cancelled one), edit, and submit. Or DUPLICATE any document into a new draft.

* A cancelled document stays on record and is hidden from lists/reports that care (the accounting reports do); the amendment is named after it: SINV-0001 -> SINV-0001-1 -> SINV-0001-2.
* A document can be amended only once, and only when cancelled.
* Both ways produce the VALUES for a new, unsaved form: nothing is created until you save it, and what may be copied is decided here, in one place.
"""
from __future__ import annotations

from .. import db
from ..db.tables import get_table
from ..exceptions import PermissionDenied, ValidationError
from ..meta.registry import registry
from sqlalchemy import select

NO_COPY = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "amended_from", "parent", "parentfield", "parenttype"}


def _row(doctype: str, name: str) -> dict | None:
    t = get_table(doctype)
    with db.transaction() as c:
        r = c.execute(select(t).where(t.c.name == name)).mappings().first()
    return dict(r) if r else None


def amendment_of(doctype: str, name: str) -> str | None:
    """The document that amends `name`, if any."""
    meta = registry.get(doctype)
    if not meta.is_submittable:
        return None
    t = get_table(doctype)
    with db.transaction() as c:
        return c.execute(select(t.c.name).where(t.c.amended_from == name).limit(1)).scalar()


def amended_name(doctype: str, original: str) -> str:
    """SINV-0001 -> SINV-0001-1; amending that one -> SINV-0001-2 (never a name that exists)."""
    row = _row(doctype, original)
    base, n = original, 1
    if row and row.get("amended_from"):
        head, _, tail = original.rpartition("-")
        if head and tail.isdigit():
            base, n = head, int(tail) + 1
    while _row(doctype, f"{base}-{n}"):
        n += 1
    return f"{base}-{n}"


def check_amendment(doctype: str, original: str) -> None:
    meta = registry.get(doctype)
    if not meta.is_submittable:
        raise ValidationError(f"{doctype} cannot be amended: it is not submittable")
    row = _row(doctype, original)
    if row is None:
        raise ValidationError(f"{doctype} {original} does not exist, so it cannot be amended")
    if row["docstatus"] != 2:
        raise ValidationError(f"Only a cancelled document can be amended; {original} is " + {0: "a draft (just edit it)", 1: "submitted (cancel it first)"}.get(row["docstatus"], "not cancelled"))
    other = amendment_of(doctype, original)
    if other:
        raise ValidationError(f"{original} has already been amended as {other}. Amend that one instead.")


def copy_values(doctype: str, name: str, mode: str) -> dict:
    """The values for a NEW, UNSAVED form copied from an existing document. mode: 'amend' or 'duplicate'."""
    from . import get_doc
    from ..permissions import has_permission
    if mode not in ("amend", "duplicate"):
        raise ValidationError("mode must be 'amend' or 'duplicate'")
    meta = registry.get(doctype)
    if meta.istable:
        raise ValidationError("A child row cannot be copied on its own")
    doc = get_doc(doctype, name)                                        # raises if you may not read it
    if not has_permission(meta, "create"):
        raise PermissionDenied(f"You may not create {doctype}, so you cannot {mode} one")
    if mode == "amend":
        check_amendment(doctype, name)
    suggested = amended_name(doctype, name) if mode == "amend" else None
    data = doc.as_dict()
    values: dict = {}
    for f in meta.fields:
        if f.fieldname in NO_COPY or f.is_layout:
            continue
        if f.is_table:
            values[f.fieldname] = [{k: v for k, v in row.items() if k not in NO_COPY} for row in data.get(f.fieldname) or []]
        elif f.has_column:
            values[f.fieldname] = None if f.unique else data.get(f.fieldname)         # a unique value (a code, a number) must be chosen again
    a = meta.autoname or ""
    if mode == "amend":
        values["amended_from"] = name
        if a.startswith("field:"):
            values[a[6:]] = suggested                                                 # the field that IS the name carries the amended name
    return {"doctype": doctype, "mode": mode, "source": name, "values": values, "amended_from": name if mode == "amend" else None, "suggested_name": suggested}
