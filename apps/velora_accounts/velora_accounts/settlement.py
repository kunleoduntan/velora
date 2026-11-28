"""Settling invoices from a Receipt (customer) or a Payment (supplier): validation, and applying/undoing it under row locks."""
from __future__ import annotations

from decimal import Decimal

from velora import throw

from . import common as c, invoices

ZERO = Decimal("0")


def prepare(doc, invoice_dt: str, party_field: str, total: Decimal) -> tuple[Decimal, Decimal]:
    """Validate the allocation rows of a Receipt/Payment. Returns (allocated, discount). Fills each row's snapshot fields."""
    rows = list(doc.invoices or [])
    if not rows:
        return ZERO, ZERO
    if not doc.party:
        throw(f"Choose the {'customer' if party_field == 'customer' else 'supplier'} before settling invoices")
    seen, alloc, disc = set(), ZERO, ZERO
    for n, r in enumerate(rows, 1):
        if not r.invoice:
            throw(f"Invoice row {n}: choose an invoice")
        if r.invoice in seen:
            throw(f"Invoice row {n}: {r.invoice} appears twice")
        seen.add(r.invoice)
        a, d = c.money(r.allocated or 0, f"Invoice row {n} settle"), c.money(r.discount or 0, f"Invoice row {n} discount")
        if a < 0 or d < 0:
            throw(f"Invoice row {n}: amounts cannot be negative")
        if a + d == 0:
            throw(f"Invoice row {n}: enter the amount to settle")
        inv = invoices.invoice_facts(invoice_dt, r.invoice)
        if inv is None or inv["docstatus"] != 1:
            throw(f"Invoice row {n}: {invoice_dt} {r.invoice} is not a submitted invoice")
        if inv[party_field] != doc.party:
            throw(f"Invoice row {n}: {r.invoice} belongs to {inv[party_field]}, not {doc.party}")
        out = c.D(inv["outstanding"])
        if a + d > out:
            throw(f"Invoice row {n}: {r.invoice} has only {out:,.2f} outstanding, but {a + d:,.2f} is being settled")
        r.allocated, r.discount, r.outstanding, r.invoice_date, r.due_date = a, d, out, inv["posting_date"], inv["due_date"]
        alloc, disc = alloc + a, disc + d
    if alloc > total:
        throw(f"The invoices settle {alloc:,.2f} but the amount is only {total:,.2f}")
    return alloc, disc


def apply(doc, invoice_dt: str, sign: int) -> None:
    """sign=+1 on submit (reduce outstanding), -1 on cancel (give it back). Invoices are locked in name order so concurrent documents cannot deadlock."""
    for r in sorted(doc.invoices or [], key=lambda x: x.invoice):
        amt = c.D(r.allocated) + c.D(r.discount)
        (invoices.settle if sign > 0 else invoices.unsettle)(invoice_dt, r.invoice, amt)
