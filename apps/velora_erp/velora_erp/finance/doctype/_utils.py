"""Small transactional persistence helpers for trusted document lifecycle hooks."""
from sqlalchemy import update
from velora import db
from velora.db.tables import get_table


def db_update(doc, **values):
    """Update system-calculated fields inside the current document transaction."""
    if not values:
        return
    table = get_table(doc.doctype)
    with db.transaction() as conn:
        conn.execute(update(table).where(table.c.name == doc.name).values(**values))
    for key, value in values.items():
        setattr(doc, key, value)


def db_update_child(doctype, name, **values):
    table = get_table(doctype)
    with db.transaction() as conn:
        conn.execute(update(table).where(table.c.name == name).values(**values))
