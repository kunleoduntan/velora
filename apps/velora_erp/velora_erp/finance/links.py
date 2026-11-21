"""Plain-field links between ERP documents, for the framework's "cannot cancel while something still depends on it" check.

ERP documents point at their source in two plain fields (`source_doctype` + `source_document`, or `reference_doctype` +
`reference_name`) instead of a Link field, because the source can be any of several document types. The framework finds Link
fields by itself; this provider finds these.
"""
from __future__ import annotations

from sqlalchemy import select

from velora import db
from velora.db.tables import get_table
from velora.meta.registry import registry

PAIRS = (("source_doctype", "source_document"), ("reference_doctype", "reference_name"))


def dynamic_links(doctype: str, name: str) -> list[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    with db.transaction() as conn:
        for dt in registry._doctypes.values():
            columns = {f.fieldname for f in dt.fields}
            for kind, ref in PAIRS:
                if kind not in columns or ref not in columns:
                    continue
                table = get_table(dt.name)
                if dt.istable:
                    for parent, parenttype in conn.execute(select(table.c.parent, table.c.parenttype).where(table.c[kind] == doctype, table.c[ref] == name)).all():
                        if parenttype:
                            found.add((parenttype, parent))
                else:
                    for (n,) in conn.execute(select(table.c.name).where(table.c[kind] == doctype, table.c[ref] == name)).all():
                        found.add((dt.name, n))
    return sorted(found)
