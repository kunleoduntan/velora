"""The ledger: the ONLY way money is recorded.

Rules this module enforces for every voucher, whatever document created it:
  * double entry - total debits equal total credits, exactly (Decimal, 2 places, nothing is silently rounded)
  * a line is a debit OR a credit, never both, never negative, never zero
  * only leaf, enabled accounts; Receivable/Payable accounts always carry a party, other accounts never do
  * the date must fall in an existing, open fiscal year and after the books lock date
  * a voucher can be posted once; entries are never edited or deleted - cancelling posts an exact mirror (a reversal)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update

from velora import db, new_doc, throw
from velora.db.tables import get_table

from . import common as c


@dataclass
class Leg:
    account: str
    debit: Decimal | int | str = 0
    credit: Decimal | int | str = 0
    party_type: str | None = None
    party: str | None = None
    remarks: str = ""
    cost_center: str | None = None


def fiscal_year_for(d) -> dict:
    d = c.to_date(d)
    t = get_table("Fiscal Year")
    with db.transaction() as conn:
        row = conn.execute(select(t.c.name, t.c.is_closed).where(t.c.start_date <= d, t.c.end_date >= d)).mappings().first()
    if row is None:
        throw(f"No fiscal year covers {d.isoformat()}. Create the fiscal year first.")
    return dict(row)


def check_open(d, what: str = "post to") -> str:
    """The date's fiscal year, after proving the books are open for it."""
    d = c.to_date(d)
    fy = fiscal_year_for(d)
    if fy["is_closed"]:
        throw(f"Fiscal year {fy['name']} is closed: you cannot {what} {d.isoformat()}")
    lock = c.get_lock_date()
    if lock and d <= lock:
        throw(f"The books are locked up to {lock.isoformat()}: you cannot {what} {d.isoformat()}. "
              "Post an adjustment in the open period instead (or an Accounts Manager can move the lock date).")
    return fy["name"]


def _gl():
    return get_table("GL Entry")


def voucher_rows(voucher_type: str, voucher_no: str, reversals: bool = False) -> list[dict]:
    t = _gl()
    flag = func.coalesce(t.c.is_reversal, 0)
    with db.transaction() as conn:
        q = select(t).where(t.c.voucher_type == voucher_type, t.c.voucher_no == voucher_no, flag == (1 if reversals else 0)).order_by(t.c.creation, t.c.name)
        return [dict(r) for r in conn.execute(q).mappings()]


def is_posted(voucher_type: str, voucher_no: str) -> bool:
    rows = voucher_rows(voucher_type, voucher_no)
    return bool(rows) and not any(r.get("is_cancelled") for r in rows)


def validate_legs(legs: list[Leg]) -> list[tuple[Leg, Decimal, Decimal]]:
    """The double-entry rules. Returns (leg, debit, credit) with exact amounts; raises with the row number on any problem."""
    if len(legs) < 2:
        throw("A voucher needs at least two lines")
    infos = c.accounts_info([g.account for g in legs])
    out, td, tc = [], Decimal("0"), Decimal("0")
    for n, g in enumerate(legs, 1):
        dr, cr = c.money(g.debit, f"Row {n} debit"), c.money(g.credit, f"Row {n} credit")
        if dr < 0 or cr < 0:
            throw(f"Row {n}: amounts cannot be negative")
        if dr and cr:
            throw(f"Row {n}: a line is a debit or a credit, not both")
        if not dr and not cr:
            throw(f"Row {n}: a line needs a debit or a credit amount")
        info = c.check_postable(infos.get(g.account), g.account, f"Row {n}")
        allowed = c.PARTY_RULES.get(info.get("account_type") or "")
        if allowed:
            if not g.party:
                throw(f"Row {n}: {g.account} is a {info['account_type']} account, so a {' / '.join(allowed)} is required")
            if g.party_type not in allowed:
                throw(f"Row {n}: party type for {g.account} must be {' or '.join(allowed)}, not {g.party_type or 'blank'}")
        elif g.party or g.party_type:
            throw(f"Row {n}: {g.account} is not a Receivable/Payable account, so it cannot carry a party")
        td, tc = td + dr, tc + cr
        out.append((g, dr, cr))
    c.require_parties((g.party_type, g.party) for g, _, _ in out)
    if td != tc:
        throw(f"Debits ({td}) and credits ({tc}) must be equal; the difference is {td - tc}")
    if td == 0:
        throw("A voucher cannot be zero")
    return out


def post(voucher_type: str, voucher_no: str, posting_date, legs: list[Leg], remarks: str = "") -> int:
    rows = validate_legs(legs)
    fy = check_open(posting_date)
    pd = c.to_date(posting_date)
    debits = [g.account for g, dr, _ in rows if dr]
    credits = [g.account for g, _, cr in rows if cr]
    with db.transaction():          # ATOMIC however it is called: a voucher is posted whole or not at all (a document's own transaction is joined)
        if voucher_rows(voucher_type, voucher_no):
            throw(f"{voucher_type} {voucher_no} has already been posted to the ledger")
        for g, dr, cr in rows:
            opposite = credits if dr else debits
            new_doc("GL Entry", posting_date=pd, account=g.account, debit=dr, credit=cr, party_type=g.party_type or None, party=g.party or None,
                    voucher_type=voucher_type, voucher_no=voucher_no, against=", ".join(dict.fromkeys(opposite))[:255], remarks=(g.remarks or remarks or "")[:140],
                    cost_center=g.cost_center, fiscal_year=fy, is_reversal=0).insert(ignore_permissions=True)
    return len(rows)


def cancel_voucher(voucher_type: str, voucher_no: str, remarks: str = "") -> int:
    """Cancel a posted voucher the way ERPNext does: its entries (and their exact opposites, so any raw sum still nets to zero) are FLAGGED cancelled and disappear from
    reports unless you choose to show cancelled entries. Nothing is deleted and no amount is ever changed; correcting a mistake is cancel -> amend -> submit.
    Refused if that period is closed or locked."""
    with db.transaction():          # atomic however it is called: all of it or none of it
        originals = voucher_rows(voucher_type, voucher_no)
        if not originals:
            return 0                                           # nothing was ever posted (e.g. cancelling a document that never posted)
        if any(r.get("is_cancelled") for r in originals):
            throw(f"{voucher_type} {voucher_no} has already been cancelled")
        check_open(originals[0]["posting_date"], "cancel an entry dated")
        for r in originals:
            new_doc("GL Entry", posting_date=r["posting_date"], account=r["account"], debit=r["credit"], credit=r["debit"], party_type=r["party_type"], party=r["party"],
                    voucher_type=voucher_type, voucher_no=voucher_no, against=r["against"], remarks=(f"Cancelled: {remarks}" if remarks else "Cancelled")[:140],
                    cost_center=r["cost_center"], fiscal_year=r["fiscal_year"], is_reversal=1, reversal_of=r["name"], is_cancelled=1).insert(ignore_permissions=True)
        t = _gl()
        db.conn().execute(update(t).where(t.c.name.in_([r["name"] for r in originals])).values(is_cancelled=1))        # the ONLY change a ledger entry may ever undergo
        return len(originals)


reverse = cancel_voucher        # the old name still works


def live():
    """SQL condition: the entry is not cancelled (an old row with no flag counts as live)."""
    return func.coalesce(_gl().c.is_cancelled, 0) == 0


def balance(account: str, as_of=None, party: str | None = None) -> Decimal:
    """Net debit balance (debits - credits) of an account, optionally for one party and up to a date. Cancelled entries are not counted."""
    t = _gl()
    with db.transaction() as conn:
        q = select(func.coalesce(func.sum(t.c.debit), 0) - func.coalesce(func.sum(t.c.credit), 0)).where(t.c.account == account, live())
        if as_of:
            q = q.where(t.c.posting_date <= c.to_date(as_of))
        if party:
            q = q.where(t.c.party == party)
        return Decimal(str(conn.execute(q).scalar() or 0))
