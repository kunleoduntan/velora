"""General Ledger Analytical Review (ISA 520 style): compare a period with an earlier one and point at what an auditor would ask about.

Read-only. It works from the posted ledger (Account Ledger Record), in base currency, so reversals are already netted in.
Every finding says WHY it was raised; none of them is an accusation, only a question worth asking.
"""
from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from velora import db, throw
from velora.db.tables import get_table

ZERO = Decimal("0")
SUSPENSE_WORDS = ("suspense", "clearing", "holding", "interim", "unallocated", "unidentified")
ROUND_STEP = Decimal("100000")


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


def _day(v, label) -> date:
    try:
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])
    except ValueError:
        throw(f"{label} must look like 2026-12-31.")


def _rows(start: date, end: date) -> list[dict]:
    t = get_table("Account Ledger Record")
    q = select(t.c.account, t.c.account_code_snapshot, t.c.account_name_snapshot, t.c.root_type_snapshot, t.c.posting_date, t.c.base_debit, t.c.base_credit, t.c.source_doctype,
               t.c.source_name, t.c.posting_event, t.c.line_description).where(t.c.posting_date >= start, t.c.posting_date <= end)
    with db.transaction() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


def _by_account(rows) -> dict:
    out: dict = {}
    for r in rows:
        a = out.setdefault(r["account"], {"account": r["account"], "code": r["account_code_snapshot"] or "", "name": r["account_name_snapshot"] or r["account"], "root_type": r["root_type_snapshot"] or "", "net": ZERO, "debit": ZERO, "credit": ZERO})
        a["debit"] += _d(r["base_debit"])
        a["credit"] += _d(r["base_credit"])
        a["net"] += _d(r["base_debit"]) - _d(r["base_credit"])
    return out


def _f(v):
    return float(round(v, 2))


def run_review(from_date, to_date, prior_from, prior_to, *, threshold_pct=50, min_amount=10000, top=40) -> dict:
    start, end, pstart, pend = _day(from_date, "From date"), _day(to_date, "To date"), _day(prior_from, "Prior from date"), _day(prior_to, "Prior to date")
    if start > end or pstart > pend:
        throw("A period cannot end before it starts.")
    if pend >= start and pstart <= end:
        throw("The comparison period overlaps the period under review. Choose an earlier one.")
    threshold, floor = Decimal(str(threshold_pct)), Decimal(str(min_amount))
    if threshold < 0 or floor < 0:
        throw("The thresholds cannot be negative.")
    cur_rows, prior_rows = _rows(start, end), _rows(pstart, pend)
    cur, prior = _by_account(cur_rows), _by_account(prior_rows)

    accounts, flagged = [], []
    for key in sorted(set(cur) | set(prior)):
        c, p = cur.get(key), prior.get(key)
        now_v, then_v = (c["net"] if c else ZERO), (p["net"] if p else ZERO)
        base = c or p
        pct = ((now_v - then_v) / abs(then_v) * 100) if then_v else (Decimal(100) if now_v else ZERO)
        reasons = []
        if c and not p and abs(now_v) >= floor:
            reasons.append("New account with significant activity")
        if p and not c and abs(then_v) >= floor:
            reasons.append("Active in the earlier period but silent in this one")
        if c and p and abs(pct) >= threshold and max(abs(now_v), abs(then_v)) >= floor:
            reasons.append(f"{abs(round(pct, 1))}% {'increase' if pct > 0 else 'decrease'} on the earlier period")
        if c and base["root_type"] == "Income" and now_v > 0:
            reasons.append("An income account has a net debit: check the classification")
        if c and base["root_type"] == "Expense" and now_v < 0:
            reasons.append("An expense account has a net credit: possible write-back or reversal")
        row = {"account": key, "code": base["code"], "name": base["name"], "root_type": base["root_type"], "current": _f(now_v), "prior": _f(then_v), "change": _f(now_v - then_v),
               "change_percent": float(round(pct, 1)), "reasons": reasons}
        accounts.append(row)
        if reasons:
            flagged.append(row)
    accounts.sort(key=lambda r: -abs(r["change"]))
    flagged.sort(key=lambda r: -abs(r["change"]))

    suspense = [{"account": r["account"], "date": str(r["posting_date"]), "document": f'{r["source_doctype"]} {r["source_name"]}', "debit": _f(_d(r["base_debit"])), "credit": _f(_d(r["base_credit"])), "description": r["line_description"] or ""}
                for r in cur_rows if any(w in (r["account_name_snapshot"] or "").lower() for w in SUSPENSE_WORDS)]
    suspense.sort(key=lambda r: -(r["debit"] + r["credit"]))

    months: dict = defaultdict(lambda: {"total": ZERO, "last3": ZERO})
    for r in cur_rows:
        if r["posting_event"] in ("Opening Balance",):
            continue
        d, amt = r["posting_date"], _d(r["base_debit"])
        m = months[(d.year, d.month)]
        m["total"] += amt
        if d.day > monthrange(d.year, d.month)[1] - 3:
            m["last3"] += amt
    period_end = [{"month": f"{y}-{mo:02d}", "total": _f(v["total"]), "last_three_days": _f(v["last3"]), "share_percent": float(round(v["last3"] / v["total"] * 100, 1)) if v["total"] else 0.0,
                   "reason": "Over 40% of the month's postings fall in its last three days" if v["total"] and v["last3"] / v["total"] > Decimal("0.4") else ""} for (y, mo), v in sorted(months.items())]

    journals = [r for r in cur_rows if "journal" in (r["source_doctype"] or "").lower()]
    by_doc: dict = defaultdict(lambda: {"amount": ZERO, "date": None})
    for r in journals:
        k = f'{r["source_doctype"]} {r["source_name"]}'
        by_doc[k]["amount"] += _d(r["base_debit"])
        by_doc[k]["date"] = r["posting_date"]
    journal_flags = []
    for k, v in by_doc.items():
        why = []
        if v["date"].weekday() >= 5:
            why.append("Posted on a weekend")
        if v["amount"] >= ROUND_STEP and v["amount"] % ROUND_STEP == 0:
            why.append("Round amount")
        if v["amount"] >= floor * 10:
            why.append("Large manual journal")
        if why:
            journal_flags.append({"document": k, "date": str(v["date"]), "amount": _f(v["amount"]), "reasons": why})
    journal_flags.sort(key=lambda r: -r["amount"])

    return {
        "period": {"from": str(start), "to": str(end), "prior_from": str(pstart), "prior_to": str(pend), "threshold_percent": float(threshold), "minimum_amount": float(floor)},
        "summary": {"accounts_current": len(cur), "accounts_prior": len(prior), "flagged": len(flagged), "suspense_lines": len(suspense), "journals_flagged": len(journal_flags),
                    "months_clustered": sum(1 for m in period_end if m["reason"])},
        "flagged_accounts": flagged[:top * 3], "top_movements": accounts[:top], "suspense": suspense[:top], "period_end": period_end, "journals": journal_flags[:top],
    }
