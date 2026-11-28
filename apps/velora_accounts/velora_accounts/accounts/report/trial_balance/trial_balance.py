from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from velora import db
from velora.db.tables import get_table
from velora.reporting import Column, ReportBuilder

from .... import common as c

COLS = [Column("account", "Account"), Column("od", "Opening Debit", "Currency"), Column("oc", "Opening Credit", "Currency"),
        Column("pd", "Debit", "Currency"), Column("pc", "Credit", "Currency"), Column("cd", "Closing Debit", "Currency"), Column("cc", "Closing Credit", "Currency")]


def trial_balance_data(from_date, to_date):
    """{account: (opening_net, period_debit, period_credit)} - opening for Income/Expense accounts starts at the fiscal year's first day."""
    g, a = get_table("GL Entry"), get_table("Account")
    fy_start = None
    try:
        fy = get_table("Fiscal Year")
        with db.transaction() as conn:
            r = conn.execute(select(fy.c.start_date).where(fy.c.start_date <= from_date, fy.c.end_date >= from_date)).first()
        fy_start = r[0] if r else None
    except Exception:  # noqa: BLE001 - no fiscal year: balance-sheet logic only
        pass
    out, unclosed = {}, Decimal(0)
    with db.transaction() as conn:
        roots = {r["name"]: r["root_type"] for r in conn.execute(select(a.c.name, a.c.root_type)).mappings()}
        q = select(g.c.account, g.c.posting_date, func.sum(g.c.debit).label("d"), func.sum(g.c.credit).label("c")).where(g.c.posting_date <= to_date, func.coalesce(g.c.is_cancelled, 0) == 0).group_by(g.c.account, g.c.posting_date)
        for r in conn.execute(q).mappings():
            acc, pd, d, cr = r["account"], r["posting_date"], Decimal(str(r["d"] or 0)), Decimal(str(r["c"] or 0))
            o, p_d, p_c = out.setdefault(acc, [Decimal(0), Decimal(0), Decimal(0)])
            if pd >= from_date:
                out[acc][1] += d
                out[acc][2] += cr
            elif roots.get(acc) in ("Income", "Expense") and fy_start and pd < fy_start:
                unclosed += d - cr                             # prior years' P&L: not in this year's opening, but it must not vanish (see below)
            else:
                out[acc][0] += d - cr
    return out, unclosed


def execute(filters):
    today = date.today()
    f = c.to_date(filters.get("from_date") or date(today.year, 1, 1))
    t = c.to_date(filters.get("to_date") or today)
    data, unclosed = trial_balance_data(f, t)
    a = get_table("Account")
    with db.transaction() as conn:
        accts = {r["name"]: dict(r) for r in conn.execute(select(a.c.name, a.c.parent_account, a.c.root_type, a.c.is_group, a.c.account_number)).mappings()}
    kids = {}
    for n, r in accts.items():
        kids.setdefault(r["parent_account"], []).append(n)
    split = lambda net: (float(net) if net > 0 else 0.0, float(-net) if net < 0 else 0.0)

    def active(n):                                             # a branch is shown if any account under it has activity
        return n in data and any(data[n]) or any(active(k) for k in kids.get(n, []))

    rb = ReportBuilder("Trial Balance", COLS, subtitle=f"{f.strftime('%-d %b %Y')} to {t.strftime('%-d %b %Y')}")

    def walk(n, depth):
        if not active(n):
            return
        r = accts[n]
        label = f"{r['account_number'] + ' - ' if r['account_number'] else ''}{n}"
        if r["is_group"]:
            rb.row({"account": label}, indent=depth)
            for k in sorted(kids.get(n, [])):
                walk(k, depth + 1)
        else:
            o, pd, pc = data.get(n, [Decimal(0)] * 3)
            od, oc = split(o)
            cd, cc = split(o + pd - pc)
            rb.row({"account": label, "od": od, "oc": oc, "pd": float(pd), "pc": float(pc), "cd": cd, "cc": cc}, indent=depth)

    for root in sorted(kids.get(None, []), key=lambda n: ["Asset", "Liability", "Equity", "Income", "Expense"].index(accts[n]["root_type"])):
        if active(root):
            rb.section(root)
            for k in sorted(kids.get(root, [])):
                walk(k, 1)
            rb.subtotal(f"Total {root}")
    if unclosed:                                                # prior-year result not yet closed into Retained Earnings by a Year-End Closing journal
        rb.section("Prior years' result not yet closed")
        od, oc = split(unclosed)
        rb.row({"account": "Unclosed profit/loss of earlier fiscal years (run a Year-End Closing journal)", "od": od, "oc": oc, "cd": od, "cc": oc}, indent=1)
        rb.subtotal("Total unclosed")
    rb.total("TOTAL")
    return rb
