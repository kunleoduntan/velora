"""Cycle counting: count a few items often (fast movers more often than slow ones) instead of the whole store once a year.

Items carry an ABC class. Inventory Settings says how many days may pass between counts of each class. 'Generate' fills a Cycle Count
with the items in a warehouse that are due; 'Post' turns the counted quantities into a draft Stock Reconciliation, which goes through
the company's normal approval before stock and ledger change.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from velora import get_doc, get_list, new_doc, throw
from velora_erp.finance.inventory.controls import controls

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def due_items(warehouse: str, as_of: date | None = None) -> list[dict]:
    """Stock items held in the warehouse whose last count is older than their class interval (never-counted items are always due)."""
    from velora_erp.finance.inventory.reservations import on_hand
    day = as_of or date.today()
    cfg = controls()
    interval = {"A": int(cfg["cycle_count_days_a"]), "B": int(cfg["cycle_count_days_b"]), "C": int(cfg["cycle_count_days_c"])}
    out = []
    items = get_list("Inventory Item", filters={"is_stock_item": 1, "disabled": 0},
                     fields=["name", "abc_class", "last_counted_on", "tracking_mode"], limit=100000, ignore_permissions=True)
    for it in items:
        qty = on_hand(it["name"], warehouse)
        if qty == 0:
            continue
        cls = (it.get("abc_class") or "C").upper()
        last = it.get("last_counted_on")
        if last and str(last) > (day - timedelta(days=interval.get(cls, interval["C"]))).isoformat():
            continue
        out.append({"item_code": it["name"], "abc_class": cls, "system_qty": float(qty), "serial": it.get("tracking_mode") == "Serial Number", "batch": it.get("tracking_mode") == "Batch"})
    return sorted(out, key=lambda r: ({"A": 0, "B": 1}.get(r["abc_class"], 2), r["item_code"]))


def generate(doc) -> int:
    """Fill the count sheet. Serial-tracked items are not counted this way (count them by serial number in a Stock Reconciliation)."""
    if not doc.warehouse:
        throw("Choose the warehouse to count first.")
    if doc.status == "Posted":
        throw("This count is already posted.")
    from velora_erp.finance.inventory.ledger import get_stock_balance
    lines = []
    for row in due_items(doc.warehouse, _date(doc.count_date)):
        if row["serial"]:
            continue
        if row["batch"]:
            from sqlalchemy import select, func
            from velora import db
            from velora.db.tables import get_table
            t = get_table("Stock Ledger Record")
            with db.transaction() as c:
                for b, q in c.execute(select(t.c.batch, func.sum(t.c.actual_qty)).where(t.c.item_code == row["item_code"], t.c.warehouse == doc.warehouse).group_by(t.c.batch)).all():
                    if b and q:
                        lines.append({"item_code": row["item_code"], "batch": b, "abc_class": row["abc_class"], "system_qty": float(q)})
        else:
            lines.append({"item_code": row["item_code"], "abc_class": row["abc_class"], "system_qty": row["system_qty"]})
    doc.set("lines", lines)
    doc.status = "Counting" if lines else "Draft"
    return len(lines)


def _date(v):
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10]) if v else None


def post(doc):
    """Create the draft Stock Reconciliation for the lines that were counted. Uncounted lines are left out."""
    if doc.status == "Posted":
        throw("This count is already posted.")
    counted = [ln for ln in doc.lines or [] if ln.counted_qty not in (None, "")]
    if not counted:
        throw("Enter the counted quantity on at least one line first.")
    from velora_erp.finance.inventory.ledger import get_stock_balance
    items = []
    for ln in counted:
        bal = get_stock_balance(ln.item_code, doc.warehouse, ln.batch or None, None)
        items.append({"item_code": ln.item_code, "batch": ln.batch or None, "physical_qty": float(_d(ln.counted_qty)), "proposed_rate": float(bal["rate"] or 0)})
    rec = new_doc("Stock Reconciliation", posting_date=date.today(), warehouse=doc.warehouse, items=items,
                  remarks=f"Cycle Count {doc.name}" + (f". {doc.remarks}" if doc.remarks else "")).insert()
    from velora import db
    from velora.db.tables import get_table
    from sqlalchemy import update
    item_t = get_table("Inventory Item")
    with db.transaction() as c:
        for code in {ln.item_code for ln in counted}:
            c.execute(update(item_t).where(item_t.c.name == code).values(last_counted_on=_date(doc.count_date) or date.today()))
    doc.stock_reconciliation = rec.name
    doc.status = "Posted"
    return rec
