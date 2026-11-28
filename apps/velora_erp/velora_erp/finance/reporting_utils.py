"""Small helpers shared by Finance reports."""
from datetime import date
from sqlalchemy import select
from velora.db.tables import get_table
from velora import db


def financial_year_start(as_of: date) -> date:
    """Resolve the configured financial year start covering the report end date."""
    table = get_table("Financial Year")
    with db.transaction() as conn:
        rows = conn.execute(
            select(table.c.start_date)
            .where(table.c.start_date <= as_of, table.c.end_date >= as_of)
            .order_by(table.c.start_date.desc())
            .limit(2)
        ).all()
    if len(rows) == 1:
        return rows[0][0]
    return date(as_of.year, 1, 1)
