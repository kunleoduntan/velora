"""Bulk actions on many documents. Each document runs in its own transaction with the full
lifecycle and permission checks, so one failure never blocks (or half-applies) the others."""
from . import db
from .document import get_doc
from .exceptions import ValidationError, VeloraError
from .meta.registry import registry

BULK_MAX = 500
ACTIONS = ("delete", "submit", "cancel", "update")


def bulk_action(doctype: str, action: str, names: list, values: dict | None = None) -> list[dict]:
    meta = registry.get(doctype)
    if action not in ACTIONS:
        raise ValidationError(f"Unknown bulk action {action!r}")
    if not names:
        raise ValidationError("No documents selected")
    if len(names) > BULK_MAX:
        raise ValidationError(f"Bulk actions are limited to {BULK_MAX} documents at a time")
    if action == "update":
        allowed = {f.fieldname for f in meta.value_fields if not f.read_only}
        bad = [k for k in (values or {}) if k not in allowed]
        if not values or bad:
            raise ValidationError(f"Bulk update needs editable fields; not allowed: {bad or 'nothing given'}")
    results = []
    for name in dict.fromkeys(names):
        try:
            with db.transaction():
                doc = get_doc(doctype, name)
                if action == "update":
                    doc.update(values)
                    doc.save()
                else:
                    getattr(doc, action)()
            results.append({"name": name, "ok": True})
        except VeloraError as e:
            results.append({"name": name, "ok": False, "error": str(e)})
    return results
