"""Before 0.4 a cancelled voucher was undone by posting visible reversal lines. Flag those vouchers (the originals AND their reversal lines) as cancelled, so the
reports show the same tidy ledger as a voucher cancelled today. Amounts are not touched: only the flag changes, which the database rule allows."""
from sqlalchemy import func, select, update

from velora import db
from velora.db.tables import get_table


def execute():
    t = get_table("GL Entry")
    with db.transaction() as conn:
        vouchers = conn.execute(select(t.c.voucher_type, t.c.voucher_no).where(t.c.is_reversal == 1).distinct()).all()
        for vt, vn in vouchers:
            conn.execute(update(t).where(t.c.voucher_type == vt, t.c.voucher_no == vn, func.coalesce(t.c.is_cancelled, 0) == 0).values(is_cancelled=1))      # only rows not flagged yet: safe to re-run
