"""Upgrade: 21 DocTypes lost the "Administrative " prefix (Administrative Request is now Request, and so on).

Runs before the schema sync. When the old table exists and the new one does not, the table is renamed (rows, indexes and all) and the
`parenttype` of child rows is updated. Safe to run again."""
import json
from pathlib import Path

from sqlalchemy import inspect, text

from velora import db
from velora.db.tables import table_name

RENAMED = json.loads((Path(__file__).with_name("renamed.json")).read_text())


def execute():
    with db.transaction() as conn:
        insp = inspect(conn)
        tables = set(insp.get_table_names())
        for old, new in RENAMED.items():
            o, n = table_name(old), table_name(new)
            if o in tables and n not in tables:
                conn.execute(text(f'ALTER TABLE "{o}" RENAME TO "{n}"'))
                tables.discard(o)
                tables.add(n)
            # a child table's rows say which DocType they belong to
        for t in tables:
            cols = {c["name"] for c in insp.get_columns(t)} if t in tables else set()
            if "parenttype" in cols:
                for old, new in RENAMED.items():
                    conn.execute(text(f'UPDATE "{t}" SET parenttype = :n WHERE parenttype = :o'), {"n": new, "o": old})
