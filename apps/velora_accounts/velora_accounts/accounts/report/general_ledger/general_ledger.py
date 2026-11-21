from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from velora import db, throw
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder

from .... import common as c

MAX_ROWS = 5000


def execute(filters):
    today = date.today()
    f, t = c.to_date(filters.get("from_date") or date(today.year, 1, 1)), c.to_date(filters.get("to_date") or today)
    account, party = filters.get("account") or None, (filters.get("party") or "").strip() or None
    if not account and not party:
        throw("Choose an account and/or a customer/supplier")
    g = get_table("GL Entry")
    show_cancelled = str(filters.get("show_cancelled") or "").lower() in ("1", "true", "yes")
    cond = [g.c.account == account] if account else []
    if not show_cancelled:
        cond.append(func.coalesce(g.c.is_cancelled, 0) == 0)                     # a cancelled voucher leaves the ledger view (it is still on record)
    if party:
        cond.append(g.c.party == party)
    with db.transaction() as conn:
        o = conn.execute(select(func.coalesce(func.sum(g.c.debit), 0), func.coalesce(func.sum(g.c.credit), 0)).where(*cond, g.c.posting_date < f)).first()
        rows = conn.execute(select(g).where(*cond, g.c.posting_date >= f, g.c.posting_date <= t).order_by(g.c.posting_date, g.c.creation, g.c.name).limit(MAX_ROWS + 1)).mappings().all()
    if len(rows) > MAX_ROWS:
        throw(f"More than {MAX_ROWS} entries: narrow the dates")
    title = " / ".join(x for x in (account, party) if x)
    rb = ReportBuilder(f"General Ledger - {title}", [Column("date", "Date"), Column("voucher", "Voucher"), Column("account", "Account"), Column("party", "Party"),
                                                    Column("remarks", "Remarks"), Column("debit", "Debit", "Currency"), Column("credit", "Credit", "Currency"), Column("balance", "Balance", "Currency")])
    bal = Decimal(str(o[0])) - Decimal(str(o[1]))
    rb.row({"remarks": "Opening balance", "balance": bal})
    td = tc = Decimal(0)
    for r in rows:
        d, cr = Decimal(str(r["debit"])), Decimal(str(r["credit"]))
        bal += d - cr
        td, tc = td + d, tc + cr
        rb.row({"date": r["posting_date"].isoformat(), "voucher": f"{r['voucher_type']} {r['voucher_no']}" + (" (cancelled)" if r["is_cancelled"] else ""), "account": r["account"],
                "party": r["party"] or "", "remarks": r["remarks"] or "", "debit": d or None, "credit": cr or None, "balance": bal})
    rb.row({"remarks": "Totals / closing balance", "debit": td, "credit": tc, "balance": bal})
    return rb
