"""Expose safe, permission-aware correction actions for a document."""
from __future__ import annotations
from ..exceptions import ValidationError
from ..meta.registry import registry
from ..permissions import has_permission
from .document import get_doc
from .amend import amendment_of


def correction_options(doctype: str, name: str) -> dict:
    meta = registry.get(doctype)
    doc = get_doc(doctype, name)  # read permission is checked by get_doc
    status = int(doc.docstatus or 0)
    can_create = has_permission(meta, "create")
    can_cancel = status == 1 and has_permission(meta, "cancel")
    can_amend = bool(meta.is_submittable and status == 2 and can_create and not amendment_of(doctype, name))
    can_duplicate = can_create and not meta.istable
    return {
        "doctype": doctype,
        "name": name,
        "docstatus": status,
        "actions": {
            "edit": status == 0 and has_permission(meta, "write"),
            "cancel": can_cancel,
            "amend": can_amend,
            "duplicate": can_duplicate,
            "delete": status == 0 and has_permission(meta, "delete"),
        },
        "amended_to": amendment_of(doctype, name) if meta.is_submittable else None,
        "policy": "cancel_amend_duplicate",
    }
