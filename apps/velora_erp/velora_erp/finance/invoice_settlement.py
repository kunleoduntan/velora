"""Invoice settlement for Receipts and Payments (Peachtree-style "apply to invoices").

A Receipt or Payment line that carries an ``invoice_reference`` and an ``allocation_amount`` settles that
invoice. This module is the single place that

* validates the allocation (submitted + approved invoice, same party, same currency, not more than the
  invoice's outstanding balance, no invoice settled twice in one document),
* applies it on submit under ``SELECT ... FOR UPDATE`` row locks taken in name order, so two documents
  settling the same invoice at once serialise instead of over-settling or deadlocking,
* releases it again when the document is reversed,
* suggests allocations (oldest due first) for the "Apply to Invoices" screen.

Outstanding = Invoice Total - Amount Settled. Cash discount and withholding tax need no special field: they
are ordinary lines on the same document (a Debit line to the discount / WHT receivable account) that reduce
the cash movement, while the control-account line carries the gross amount cleared against the invoice.
Cash received beyond the allocated amount stays unapplied on the party account (an advance on account).
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, update

from velora import db, throw
from velora.db.tables import get_table

ZERO = Decimal("0")

# (direction, purpose) -> (invoice doctype, party type). Only these purposes settle invoices.
SETTLES = {
    ("Receipt", "Customer Receipt"): ("Sales Invoice", "Customer"),
    ("Payment", "Supplier Payment"): ("Purchase Invoice", "Supplier"),
    ("Payment", "Expense Payment"): ("Purchase Invoice", "Supplier"),
}


def _d(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else 0))


def status_for(total, settled) -> str:
    total, settled = _d(total), _d(settled)
    if settled <= 0:
        return "Unpaid"
    return "Paid" if settled >= total else "Partly Paid"


def _expected_side(direction):
    return "Credit" if direction == "Receipt" else "Debit"


def allocation_rows(doc, direction):
    """Return [(line_no, invoice, amount, party)] for every allocating line."""
    rows = []
    for index, line in enumerate(doc.lines or [], 1):
        amount = _d(line.allocation_amount)
        if amount <= 0 and not line.invoice_reference:
            continue
        rows.append((index, (line.invoice_reference or "").strip(), amount, line.party, line))
    return rows


def _invoice_row(invoice_doctype, name, *, lock=False):
    table = get_table(invoice_doctype)
    query = select(table).where(table.c.name == name)
    if lock:
        query = query.with_for_update()
    with db.transaction() as conn:
        found = conn.execute(query).mappings().first()
    return dict(found) if found else None


def outstanding_of(invoice: dict) -> Decimal:
    return _d(invoice.get("grand_total")) - _d(invoice.get("amount_settled"))


def validate_allocations(doc, direction, *, lock=False, settled_by_self=None):
    """Validate the allocation lines of a draft/submitting document. Returns {invoice: amount} (possibly empty)."""
    rows = allocation_rows(doc, direction)
    if not rows:
        return {}
    kind = SETTLES.get((direction, doc.purpose))
    if not kind:
        throw(f"Invoices cannot be settled by a {doc.purpose} {direction}. Clear the Invoice Reference and "
              "Allocation Amount, or use Customer Receipt (sales invoices) or Supplier / Expense Payment (purchase invoices).")
    invoice_doctype, party_type = kind
    side = _expected_side(direction)
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for index, name, amount, party, line in rows:
        if not name:
            throw(f"Line {index}: Invoice Reference is required when an allocation amount is entered.")
        if amount <= 0:
            throw(f"Line {index}: Allocation Amount must be greater than zero when an Invoice Reference is given.")
        if (line.entry_side or side).title() != side:
            throw(f"Line {index}: only the {side} (control account) line can settle an invoice.")
        if line.party_type != party_type or not party:
            throw(f"Line {index}: the line settling {name} must carry the {party_type}.")
        totals[name] += amount
    ordered = sorted(totals)
    for name in ordered:
        invoice = _invoice_row(invoice_doctype, name, lock=lock)
        if not invoice or invoice["docstatus"] != 1:
            throw(f"{invoice_doctype} {name} is not a submitted invoice.")
        if invoice.get("approval_status") not in (None, "Approved"):
            throw(f"{invoice_doctype} {name} is not approved.")
        owners = {party for (_, n, _, party, _) in rows if n == name}
        if owners != {invoice["party"]}:
            throw(f"{invoice_doctype} {name} belongs to {invoice['party']}, not {', '.join(sorted(map(str, owners)))}.")
        if (invoice.get("currency") or "").upper() != (doc.currency or "").upper():
            throw(f"{invoice_doctype} {name} is in {invoice.get('currency')}; this document is in {doc.currency}.")
        already_here = (settled_by_self or {}).get(name, ZERO)
        outstanding = outstanding_of(invoice) + already_here
        if totals[name] > outstanding:
            throw(f"{invoice_doctype} {name} has only {outstanding:,.2f} outstanding, but {totals[name]:,.2f} is being settled.")
    return dict(totals)


def apply_allocations(doc, direction) -> dict:
    """Called from on_submit, inside the submit transaction. Locks, re-validates and increases Amount Settled."""
    kind = SETTLES.get((direction, doc.purpose))
    if not kind or not allocation_rows(doc, direction):
        return {}
    totals = validate_allocations(doc, direction, lock=True)
    table = get_table(kind[0])
    with db.transaction() as conn:
        for name in sorted(totals):
            invoice = conn.execute(select(table).where(table.c.name == name).with_for_update()).mappings().first()
            settled = _d(invoice["amount_settled"]) + totals[name]
            if settled > _d(invoice["grand_total"]):
                throw(f"{kind[0]} {name} would be over-settled.")
            conn.execute(update(table).where(table.c.name == name)
                         .values(amount_settled=settled, payment_status=status_for(invoice["grand_total"], settled)))
    return totals


def release_allocations(doc, direction) -> dict:
    """Give the settled amounts back (used by controlled reversal)."""
    kind = SETTLES.get((direction, doc.purpose))
    if not kind or doc.allocation_status != "Applied":
        return {}
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for _, name, amount, _, _ in allocation_rows(doc, direction):
        totals[name] += amount
    table = get_table(kind[0])
    with db.transaction() as conn:
        for name in sorted(totals):
            invoice = conn.execute(select(table).where(table.c.name == name).with_for_update()).mappings().first()
            if not invoice:
                continue
            settled = max(ZERO, _d(invoice["amount_settled"]) - totals[name])
            conn.execute(update(table).where(table.c.name == name)
                         .values(amount_settled=settled, payment_status=status_for(invoice["grand_total"], settled)))
    return dict(totals)


def outstanding_invoices(party_type: str, party: str, *, as_of=None, currency: str | None = None) -> list[dict]:
    """Open invoices of one party, oldest due date first."""
    doctype = {"Customer": "Sales Invoice", "Supplier": "Purchase Invoice"}.get(party_type)
    if not doctype:
        throw("Party Type must be Customer or Supplier.")
    table = get_table(doctype)
    query = select(table).where(table.c.party == party, table.c.docstatus == 1)
    if as_of:
        query = query.where(table.c.posting_date <= as_of)
    if currency:
        query = query.where(table.c.currency == currency.upper())
    with db.transaction() as conn:
        found = [dict(r) for r in conn.execute(query).mappings()]
    result = []
    for inv in found:
        if inv.get("approval_status") not in (None, "Approved"):
            continue
        out = outstanding_of(inv)
        if out > 0:
            result.append({"invoice": inv["name"], "invoice_date": inv.get("invoice_date"), "due_date": inv.get("due_date"),
                           "currency": inv.get("currency"), "invoice_total": _d(inv["grand_total"]),
                           "amount_settled": _d(inv.get("amount_settled")), "outstanding": out,
                           "payment_status": inv.get("payment_status") or "Unpaid"})
    result.sort(key=lambda r: (str(r["due_date"] or r["invoice_date"] or ""), r["invoice"]))
    return result


STRATEGIES = ("FIFO", "Best Match", "Reference Match", "Largest First", "Smallest First")


def _exact_subset(invoices, target):
    """Find invoices whose outstanding amounts add up to exactly ``target`` (minor units). Returns a list or None."""
    cents = [int((inv["outstanding"] * 100).to_integral_value()) for inv in invoices]
    goal = int((target * 100).to_integral_value())
    reachable = {0: []}
    for index, value in enumerate(cents):
        if value <= 0 or value > goal:
            continue
        for total, picked in list(reachable.items()):
            new_total = total + value
            if new_total <= goal and new_total not in reachable:
                reachable[new_total] = picked + [index]
        if len(reachable) > 200_000:   # keep the search bounded; callers fall back to FIFO
            break
        if goal in reachable:
            return [invoices[i] for i in reachable[goal]]
    return [invoices[i] for i in reachable[goal]] if goal in reachable else None


def suggest_allocations(party_type: str, party: str, amount, *, as_of=None, currency: str | None = None,
                        method: str = "FIFO", reference_text: str | None = None) -> dict:
    """Spread ``amount`` over a party's open invoices. Anything left is an unapplied advance.

    Methods (rule based and fully explainable, not a statistical model):
      FIFO             oldest due date first.
      Best Match       the combination of open invoices that adds up exactly to the amount (so the cash clears whole
                       invoices); falls back to FIFO when no exact combination exists.
      Reference Match  invoices whose number appears in ``reference_text`` (narration, bank reference) first, then FIFO.
      Largest First / Smallest First   by outstanding balance.
    """
    if method not in STRATEGIES:
        throw(f"Allocation method must be one of: {', '.join(STRATEGIES)}.")
    total = _d(amount)
    if total <= 0:
        throw("Amount must be greater than zero.")
    open_invoices = outstanding_invoices(party_type, party, as_of=as_of, currency=currency)
    ordered, explanation = open_invoices, "Oldest due date first."
    forced = {}
    if method == "Largest First":
        ordered, explanation = sorted(open_invoices, key=lambda r: -r["outstanding"]), "Largest outstanding balance first."
    elif method == "Smallest First":
        ordered, explanation = sorted(open_invoices, key=lambda r: r["outstanding"]), "Smallest outstanding balance first."
    elif method == "Reference Match":
        text = (reference_text or "").upper()
        hits = [inv for inv in open_invoices if inv["invoice"].upper() in text]
        ordered = hits + [inv for inv in open_invoices if inv not in hits]
        explanation = (f"Matched {len(hits)} invoice number(s) found in the reference, then oldest first." if hits
                       else "No invoice number found in the reference; oldest due date first.")
    elif method == "Best Match":
        exact = _exact_subset(open_invoices, total)
        if exact:
            ordered = exact
            explanation = f"These {len(exact)} invoice(s) add up exactly to the amount."
        else:
            explanation = "No combination of invoices equals the amount exactly; oldest due date first."
    remaining = total
    lines = []
    for inv in ordered:
        if remaining <= 0:
            break
        take = min(remaining, inv["outstanding"])
        lines.append({**inv, "allocate": take})
        remaining -= take
    return {"allocations": lines, "allocated": total - remaining, "unapplied": remaining, "method": method, "explanation": explanation}


def build_lines_from_allocations(party_type: str, party: str, control_account: str, allocations: list[dict],
                                 *, unapplied=ZERO, advance_account: str | None = None) -> list[dict]:
    """Turn ``suggest_allocations`` output into document line dicts (one control line per invoice)."""
    rows = [{"account": control_account, "amount": a["allocate"], "party_type": party_type, "party": party,
             "invoice_reference": a["invoice"], "allocation_amount": a["allocate"], "settlement_reference": a["invoice"],
             "description": f"Settlement of {a['invoice']}"} for a in allocations]
    if _d(unapplied) > 0:
        # Unapplied cash stays as a credit on the party's control account (Peachtree "unapplied cash") unless
        # a separate advance account is chosen; a Customer Receipt's party line must use the control account.
        rows.append({"account": advance_account or control_account, "amount": unapplied, "party_type": party_type, "party": party,
                     "description": "Unapplied amount held as advance"})
    return rows
