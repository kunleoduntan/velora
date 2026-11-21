from datetime import timedelta

from sqlalchemy import select

from velora import Document, db, throw
from velora.db.tables import get_table

from .... import common as c


class FiscalYear(Document):
    def validate(self):
        s, e = c.to_date(self.start_date, "Start date"), c.to_date(self.end_date, "End date")
        if e <= s:
            throw("The fiscal year must end after it starts")
        if (e - s) > timedelta(days=366):
            throw("A fiscal year cannot be longer than 12 months")
        t = get_table("Fiscal Year")
        with db.transaction() as conn:
            clash = conn.execute(select(t.c.name).where(t.c.start_date <= e, t.c.end_date >= s, t.c.name != (self.name or ""))).first()
        if clash:
            throw(f"These dates overlap fiscal year {clash[0]}")
        old = self._old
        if old and bool(old.get("is_closed")) != bool(self.is_closed) and not c.has_role(*c.MANAGER_ROLES):
            throw("Only an Accounts Manager can close or reopen a fiscal year")
        if old and (old.get("start_date") != s or old.get("end_date") != e):
            from ....ledger import _gl
            g = _gl()
            with db.transaction() as conn:
                if conn.execute(select(g.c.name).where(g.c.fiscal_year == self.name).limit(1)).first():
                    throw("This fiscal year already has ledger entries, so its dates cannot change")

    def before_delete(self):
        throw("Fiscal years cannot be deleted; close them instead")
