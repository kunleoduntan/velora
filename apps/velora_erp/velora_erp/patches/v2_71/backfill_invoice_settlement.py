"""Rebuild Amount Settled / Payment Status on invoices from already-submitted Receipts and Payments.

Earlier releases stored Invoice Reference and Allocation Amount on cash document lines but never reduced the
invoice's balance. This patch adds those allocations up (skipping reversed documents) so existing invoices show
the right outstanding amount. It is idempotent: it recomputes from the cash documents each time it runs.
"""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, update

from velora import db
from velora.db.tables import get_table
from velora_erp.finance.invoice_settlement import SETTLES, status_for


def execute():
    for (direction, purpose), (invoice_doctype, _) in SETTLES.items():
        doc_t, line_t = get_table(direction), get_table(f"{direction} Line")
        inv_t = get_table(invoice_doctype)
        totals = defaultdict(Decimal)
        with db.transaction() as conn:
            docs = {r["name"]: r for r in conn.execute(select(doc_t.c.name, doc_t.c.purpose, doc_t.c.docstatus)
                                                      .where(doc_t.c.docstatus == 1, doc_t.c.purpose == purpose)).mappings()}
            for ln in conn.execute(select(line_t).where(line_t.c.parent.in_(list(docs) or [""]))).mappings():
                if not ln["invoice_reference"]:
                    continue
                totals[ln["invoice_reference"]] += Decimal(str(ln["allocation_amount"] or 0))
            for name, amount in totals.items():
                inv = conn.execute(select(inv_t).where(inv_t.c.name == name)).mappings().first()
                if not inv or inv["docstatus"] != 1:
                    continue
                settled = min(amount, Decimal(str(inv["grand_total"])))
                conn.execute(update(inv_t).where(inv_t.c.name == name)
                             .values(amount_settled=settled, payment_status=status_for(inv["grand_total"], settled)))
