"""Revaluation of foreign-currency monetary items at the closing rate (IAS 21.23 and 21.28).

Receivables, payables, bank and cash, loans and accrued items held in a foreign currency are restated to the closing rate on the reporting date.
The difference is an unrealised exchange gain or loss in profit or loss. Non-monetary items (stock, prepayments, advances, fixed assets) are not revalued.
The ledger is the only source: nothing is estimated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from velora import db, throw
from velora.db.tables import get_table

MONETARY_TYPES = ("RECEIVABLE", "PAYABLE", "BANK", "CASH", "BORROWING", "ACCRUAL")
ZERO = Decimal(0)


def revaluation_rows(as_of, base: str, places: int = 2) -> list[dict]:
    from velora_erp.finance.multicurrency import lookup_rate
    from velora_erp.finance.engine import _money
    led, acc = get_table("Account Ledger Record"), get_table("Account")
    q = (select(led.c.account, led.c.party_type, led.c.party, led.c.currency,
                func.sum(led.c.debit - led.c.credit).label("foreign"), func.sum(led.c.base_debit - led.c.base_credit).label("carrying"))
         .join(acc, acc.c.name == led.c.account)
         .where(led.c.posting_date <= as_of, led.c.currency != base, acc.c.account_type.in_(MONETARY_TYPES))
         .group_by(led.c.account, led.c.party_type, led.c.party, led.c.currency))
    with db.transaction() as c:
        groups = [dict(r) for r in c.execute(q).mappings()]
    rates, missing, rows = {}, set(), []
    for g in groups:
        ccy = g["currency"]
        if ccy not in rates:
            rates[ccy] = lookup_rate(ccy, base, as_of)
            if not rates[ccy]:
                missing.add(ccy)
    if missing:
        throw(f"There is no exchange rate to {base} on or before {as_of} for {', '.join(sorted(missing))}. Add it in Currency Exchange Rate, then calculate again; nothing is revalued at a guessed rate.")
    for g in groups:
        foreign, carrying, rate = Decimal(str(g["foreign"] or 0)), Decimal(str(g["carrying"] or 0)), rates[g["currency"]]
        revalued = _money(foreign * rate, places)
        diff = revalued - carrying
        if diff == 0:
            continue
        rows.append({"account": g["account"], "party_type": g["party_type"] or None, "party": g["party"] or None, "currency": g["currency"], "foreign_balance": foreign,
                     "carrying_balance": carrying, "closing_rate": rate, "revalued_balance": revalued, "difference": diff})
    return sorted(rows, key=lambda r: (r["currency"], r["account"], r["party"] or ""))


def posting_lines_by_currency(doc, gain_account: str, loss_account: str) -> dict[str, list[dict]]:
    """Per currency: each item's difference against its own account, and the net against the unrealised gain or loss account."""
    out: dict[str, list[dict]] = defaultdict(list)
    for r in doc.lines:
        d = Decimal(str(r.difference))
        if d == 0:
            continue
        out[r.currency].append({"account": r.account, "party_type": r.party_type or None, "party": r.party or None, "debit": ZERO, "credit": ZERO,
                                "base_debit" if d > 0 else "base_credit": abs(d), "fx_role": "Exchange difference",
                                "line_description": f"Revaluation of {r.currency} at {r.closing_rate} on {doc.revaluation_date}"})
    for ccy, lines in out.items():
        gain = sum((l.get("base_credit", ZERO) for l in lines), ZERO)       # items credited (liabilities up) are losses
        loss = sum((l.get("base_debit", ZERO) for l in lines), ZERO)
        # debits to items need an equal credit: a gain; credits to items need an equal debit: a loss
        gain, loss = loss, gain
        if gain:
            lines.append({"account": gain_account, "debit": ZERO, "credit": ZERO, "base_credit": gain, "fx_role": "Exchange difference", "line_description": f"Unrealised exchange gain, {ccy}"})
        if loss:
            lines.append({"account": loss_account, "debit": ZERO, "credit": ZERO, "base_debit": loss, "fx_role": "Exchange difference", "line_description": f"Unrealised exchange loss, {ccy}"})
    return out
