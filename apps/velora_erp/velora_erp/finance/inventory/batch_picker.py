"""Which batches to offer for an item on a document line.

The standard (and the one ERPs such as ERPNext/SAP follow) is: show only the batches of the item on the row, in the row's warehouse,
that still have stock and have not expired, and put them in FEFO order (the batch that expires first goes first) with FIFO (the batch
received first) as the tie-break and for batches with no expiry date. FEFO is the safer rule for perishable goods; for goods that never
expire it is exactly FIFO, so a single ordering serves both.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from velora import db
from velora.db.tables import get_table

# Documents that take stock OUT: only batches with stock are offered. Others (receipts, invoices from suppliers, opening stock) name a batch
# that is being received, so every batch of the item is offered, with or without stock.
ISSUING = {"Sales Invoice", "Sales Order", "Delivery Note", "Sales Quotation", "Purchase Return", "Stock Entry", "Stock Transfer", "Material Issue"}


def pick_batches(item_code: str, warehouse: str | None = None, text: str = "", parent_doctype: str | None = None, limit: int = 20, as_of: date | None = None) -> list[dict]:
    if not item_code:
        return []
    from velora.meta.registry import registry
    from velora.permissions import check_permission
    check_permission(registry.get("Batch"), "read")
    today = as_of or date.today()
    issuing = parent_doctype in ISSUING
    led, bt = get_table("Stock Ledger Record"), get_table("Batch")
    needle = (text or "").strip().lower()
    with db.transaction() as c:
        batches = c.execute(select(bt.c.name, bt.c.batch_number, bt.c.expiry_date, bt.c.manufacturing_date, bt.c.disabled).where(bt.c.item_code == item_code)).mappings().all()
        cond = [led.c.item_code == item_code, led.c.batch.isnot(None)]
        if warehouse:
            cond.append(led.c.warehouse == warehouse)
        stock = {r[0]: Decimal(str(r[1] or 0)) for r in c.execute(select(led.c.batch, func.sum(led.c.actual_qty)).where(*cond).group_by(led.c.batch)).all()}
        received = {r[0]: r[1] for r in c.execute(select(led.c.batch, func.min(led.c.posting_date)).where(*cond, led.c.actual_qty > 0).group_by(led.c.batch)).all()}
    rows = []
    for b in batches:
        if b["disabled"]:
            continue
        qty = stock.get(b["name"], Decimal("0"))
        expiry = b["expiry_date"]
        expired = bool(expiry and expiry < today)
        if issuing and (qty <= 0 or expired):
            continue
        label = f'{b["name"]} {b["batch_number"] or ""}'.lower()
        if needle and needle not in label:
            continue
        rows.append({"name": b["name"], "batch_number": b["batch_number"], "quantity": float(qty), "expiry_date": expiry, "received_on": received.get(b["name"]),
                     "expired": expired, "days_left": (expiry - today).days if expiry else None})
    far = date.max
    rows.sort(key=lambda r: (r["expiry_date"] or far, r["received_on"] or far, r["name"]))
    for i, r in enumerate(rows):
        r["suggested"] = bool(issuing and i == 0)
    return rows[:max(1, min(int(limit or 20), 100))]
