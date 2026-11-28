"""Upgrade: the Finance "Project" is gone; ProjectOne's Project is the only one.

Both used the same DocType name, so existing projects stay in the same table. This brings their values across to ProjectOne's fields:

* project_name -> title, budget_amount -> approved_budget;
* status Planned -> Draft, Active -> In Progress (the other statuses are the same);
* project_manager (required in ProjectOne) is filled from the record's owner, or Administrator.

Only blank values are filled, nothing is overwritten, and it is safe to run again."""
from sqlalchemy import inspect, text

from velora import db
from velora.db.tables import table_name

_STATUS = {"Planned": "Draft", "Active": "In Progress"}


def execute():
    table = table_name("Project")
    with db.transaction() as conn:
        insp = inspect(conn)
        if table not in insp.get_table_names():
            return
        cols = {c["name"] for c in insp.get_columns(table)}
        if "title" not in cols:
            return  # ProjectOne is not installed; nothing to bring across
        if "project_name" in cols:
            conn.execute(text(f'UPDATE "{table}" SET title = project_name WHERE (title IS NULL OR title = \'\') AND project_name IS NOT NULL'))
        if "budget_amount" in cols and "approved_budget" in cols:
            conn.execute(text(f'UPDATE "{table}" SET approved_budget = budget_amount WHERE approved_budget IS NULL AND budget_amount IS NOT NULL'))
        if "status" in cols:
            for old, new in _STATUS.items():
                conn.execute(text(f'UPDATE "{table}" SET status = :n WHERE status = :o'), {"n": new, "o": old})
        if "project_manager" in cols:
            owner = "owner" in cols
            expr = "COALESCE(NULLIF(owner, ''), 'Administrator')" if owner else "'Administrator'"
            conn.execute(text(f'UPDATE "{table}" SET project_manager = {expr} WHERE project_manager IS NULL OR project_manager = \'\''))
