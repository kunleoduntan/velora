"""Stock reservations: stock set aside for an order or customer cannot be issued to anyone else.

A reservation holds a quantity of an item in a warehouse (optionally one batch) until it is used, released, or its hold date
passes. Every issue (delivery, sale, transfer, stock entry) is checked against what is still unreserved; an issue made for the
document the stock is reserved for uses the reservation up instead of being blocked by it.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select, update

from velora import db, throw
from velora.db.tables import get_table

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def protecting() -> bool:
    from velora_erp.finance.inventory.controls import controls
    return bool(controls()["reservations_protect_stock"])


def _refs(source) -> set[tuple[str, str]]:
    """The documents an issue is 'for': the document itself and the order or request it came from."""
    refs = {(source.doctype, str(source.name))}
    for kind, name in ((getattr(source, "source_doctype", None), getattr(source, "source_document", None)),
                       ("Material Request", getattr(source, "material_request", None))):
        if kind and name:
            refs.add((str(kind), str(name)))
    return refs


def active(item_code: str, warehouse: str, batch: str | None = None, *, as_of: date | None = None) -> list[dict]:
    """Active, unexpired reservations on an item in a warehouse (every batch when none is given)."""
    t = get_table("Stock Reservation")
    day = as_of or date.today()
    cond = [t.c.item_code == item_code, t.c.warehouse == warehouse, t.c.status == "Active",
            or_(t.c.reserved_until.is_(None), t.c.reserved_until >= day)]
    if batch:
        cond.append(t.c.batch == batch)
    with db.transaction() as c:
        rows = c.execute(select(t).where(*cond).order_by(t.c.creation)).mappings().all()
    out = []
    for r in rows:
        left = _d(r["quantity"]) - _d(r["consumed_quantity"])
        if left > 0:
            out.append({**dict(r), "remaining": left})
    return out


def reserved_quantity(item_code: str, warehouse: str, batch: str | None = None, *, ignore_name: str | None = None, for_refs=()) -> Decimal:
    total = ZERO
    for r in active(item_code, warehouse, batch):
        if ignore_name and r["name"] == ignore_name:
            continue
        if (r["reserved_for_doctype"], r["reserved_for"]) in set(for_refs):
            continue
        total += r["remaining"]
    return total


def on_hand(item_code: str, warehouse: str, batch: str | None = None) -> Decimal:
    """Quantity in the warehouse across all batches and serial numbers (or in one batch)."""
    t = get_table("Stock Ledger Record")
    cond = [t.c.item_code == item_code, t.c.warehouse == warehouse]
    if batch:
        cond.append(t.c.batch == batch)
    with db.transaction() as c:
        return _d(c.execute(select(func.coalesce(func.sum(t.c.actual_qty), 0)).where(*cond)).scalar())


def available(item_code: str, warehouse: str, batch: str | None = None, *, ignore_name: str | None = None) -> Decimal:
    return on_hand(item_code, warehouse, batch) - reserved_quantity(item_code, warehouse, batch, ignore_name=ignore_name)


def assert_unreserved(source, item_code: str, warehouse: str, batch: str | None, quantity) -> None:
    """Refuse an issue that would eat into stock reserved for something else."""
    if not protecting():
        return
    qty = _d(quantity)
    refs = _refs(source)
    mine = [r for r in active(item_code, warehouse) if (r["reserved_for_doctype"], r["reserved_for"]) in refs]
    others = [r for r in active(item_code, warehouse) if r not in mine]
    held_warehouse = sum((r["remaining"] for r in others), ZERO)
    free = on_hand(item_code, warehouse) - held_warehouse
    if free < qty:
        names = ", ".join(sorted({f"{r['name']} ({r['reserved_for'] or 'no document'})" for r in others}))
        throw(f"{item_code}: {qty} requested but only {max(free, ZERO)} of the {on_hand(item_code, warehouse)} in {warehouse} is unreserved. "
              f"Reserved under {names}. Release or use that reservation first.")
    if batch:
        held_batch = sum((r["remaining"] for r in others if r["batch"] == batch), ZERO)
        free_batch = on_hand(item_code, warehouse, batch) - held_batch
        if free_batch < qty:
            throw(f"{item_code}: batch {batch} has {max(free_batch, ZERO)} unreserved in {warehouse}; {qty} requested. Release the reservation on that batch first.")


def consume(source, item_code: str, warehouse: str, batch: str | None, quantity) -> None:
    """An issue made for the document the stock is reserved for uses the reservation up (batch-specific ones first)."""
    refs = _refs(source)
    left = _d(quantity)
    t = get_table("Stock Reservation")
    mine = [r for r in active(item_code, warehouse) if (r["reserved_for_doctype"], r["reserved_for"]) in refs and (not r["batch"] or r["batch"] == batch)]
    mine.sort(key=lambda r: (0 if r["batch"] else 1))
    with db.transaction() as c:
        for r in mine:
            if left <= 0:
                break
            take = min(left, r["remaining"])
            used = _d(r["consumed_quantity"]) + take
            c.execute(update(t).where(t.c.name == r["name"]).values(consumed_quantity=used, status="Fulfilled" if used >= _d(r["quantity"]) else "Active"))
            left -= take


def expire_due() -> int:
    """Daily job: reservations whose hold date has passed no longer hold the stock."""
    t = get_table("Stock Reservation")
    with db.transaction() as c:
        return c.execute(update(t).where(t.c.status == "Active", t.c.reserved_until.isnot(None), t.c.reserved_until < date.today()).values(status="Expired")).rowcount


def availability_rows(warehouse: str | None = None, item_code: str | None = None) -> list[dict]:
    """On hand, reserved and available per item and warehouse (only where something is on hand or reserved)."""
    t = get_table("Stock Ledger Record")
    cond = []
    if warehouse: cond.append(t.c.warehouse == warehouse)
    if item_code: cond.append(t.c.item_code == item_code)
    with db.transaction() as c:
        stock = c.execute(select(t.c.item_code, t.c.warehouse, func.sum(t.c.actual_qty).label("qty")).where(*cond).group_by(t.c.item_code, t.c.warehouse)).all()
    rows = {}
    for item, wh, qty in stock:
        rows[(item, wh)] = {"item_code": item, "warehouse": wh, "on_hand": float(qty or 0), "reserved": 0.0}
    r = get_table("Stock Reservation")
    rc = [r.c.status == "Active", or_(r.c.reserved_until.is_(None), r.c.reserved_until >= date.today())]
    if warehouse: rc.append(r.c.warehouse == warehouse)
    if item_code: rc.append(r.c.item_code == item_code)
    with db.transaction() as c:
        held = c.execute(select(r.c.item_code, r.c.warehouse, func.sum(r.c.quantity - r.c.consumed_quantity)).where(*rc).group_by(r.c.item_code, r.c.warehouse)).all()
    for item, wh, qty in held:
        row = rows.setdefault((item, wh), {"item_code": item, "warehouse": wh, "on_hand": 0.0, "reserved": 0.0})
        row["reserved"] = float(qty or 0)
    out = []
    for row in rows.values():
        if row["on_hand"] or row["reserved"]:
            row["available"] = row["on_hand"] - row["reserved"]
            out.append(row)
    return sorted(out, key=lambda x: (x["item_code"], x["warehouse"]))
