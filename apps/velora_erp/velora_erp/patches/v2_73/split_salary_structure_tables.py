"""Move existing Salary Structure component rows into the new Earnings / Deductions & Contributions tables.

Rows used to live in one table (parentfield "components"). Earnings go to "earnings"; every other component type goes to "deductions".
Idempotent: rows already in the new tables are untouched. Row names, ordering and approval fingerprints are unchanged, so approved
and submitted structures stay approved.
"""
from sqlalchemy import update

from velora import db
from velora.db.tables import get_table


def execute():
    child = get_table("Salary Structure Component")
    with db.transaction() as conn:
        conn.execute(update(child).where(child.c.parentfield == "components", child.c.component_type == "Earning").values(parentfield="earnings"))
        conn.execute(update(child).where(child.c.parentfield == "components").values(parentfield="deductions"))
