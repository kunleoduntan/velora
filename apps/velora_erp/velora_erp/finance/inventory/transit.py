"""Two-step stock transfers: goods in transit.

A Stock Transfer with a transit warehouse moves stock out of the source warehouse when it is submitted; the stock then sits in the
transit warehouse (valued, visible, not available for sale) until Stock Transfer Receipts take it into the destination. Receiving can
be done in parts. What is not received stays in transit and shows in the Goods in Transit report, with a warning once it is overdue.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select, update

from velora import db, get_doc, get_list, new_doc, throw
from velora.db.tables import get_table

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def outstanding(transfer) -> dict[str, Decimal]:
    """Quantity still in transit per transfer line (sent less received by submitted receipts)."""
    return {str(l.name): _d(l.quantity) - _d(getattr(l, "received_quantity", 0)) for l in transfer.lines or []}


def validate_transfer(doc) -> None:
    """Rules a Stock Transfer must follow when it uses (or points at) a transit warehouse."""
    from velora_erp.finance.inventory.ledger import is_stock_item  # noqa: F401
    target = get_doc("Warehouse", doc.target_warehouse)
    if doc.transit_warehouse:
        transit = get_doc("Warehouse", doc.transit_warehouse)
        if not transit.is_transit:
            throw(f"{doc.transit_warehouse} is not a transit warehouse. Tick 'Transit warehouse' on it first.")
        if transit.disabled or transit.is_group:
            throw("Select an active leaf transit warehouse.")
        if doc.transit_warehouse in (doc.source_warehouse, doc.target_warehouse):
            throw("The transit warehouse must be different from the source and destination warehouses.")
        if any(getattr(l, "serial_number", None) for l in doc.lines or []) and False:
            pass
    elif target.is_transit:
        throw(f"{doc.target_warehouse} is a transit warehouse. Choose it as 'Send via transit warehouse' and give the real destination, "
              f"or the stock would arrive nowhere.")
    if get_doc("Warehouse", doc.source_warehouse).is_transit:
        throw("Stock in a transit warehouse is moved on with a Stock Transfer Receipt, not a new transfer.")


def refresh_status(transfer_name: str) -> str:
    """Set the transfer's status from what has been received."""
    t, lt = get_table("Stock Transfer"), get_table("Stock Transfer Line")
    with db.transaction() as c:
        lines = c.execute(select(lt.c.quantity, lt.c.received_quantity).where(lt.c.parent == transfer_name, lt.c.parenttype == "Stock Transfer")).all()
        sent = sum((_d(q) for q, _ in lines), ZERO)
        got = sum((_d(r) for _, r in lines), ZERO)
        status = "Received" if got >= sent and sent > 0 else ("Partially Received" if got > 0 else "In Transit")
        c.execute(update(t).where(t.c.name == transfer_name).values(transit_status=status))
    return status


def validate_receipt(doc) -> None:
    transfer = get_doc("Stock Transfer", doc.stock_transfer)
    if int(transfer.docstatus or 0) != 1:
        throw("Receive stock against a submitted Stock Transfer.")
    if not transfer.transit_warehouse:
        throw("This Stock Transfer moved stock directly; there is nothing in transit to receive.")
    if transfer.transit_status == "Received":
        throw("Everything on this Stock Transfer has already been received.")
    if doc.posting_date and doc.posting_date < transfer.posting_date:
        throw(f"The receiving date cannot be before the transfer date ({transfer.posting_date}).")
    doc.transit_warehouse, doc.target_warehouse = transfer.transit_warehouse, transfer.target_warehouse
    left = outstanding(transfer)
    sent = {str(l.name): l for l in transfer.lines or []}
    if not doc.lines:
        throw("Add the goods received. Use Receive Goods on the Stock Transfer to fill it in.")
    seen = set()
    for index, line in enumerate(doc.lines, 1):
        key = str(line.transfer_line or "")
        original = sent.get(key)
        if original is None:
            throw(f"Line {index}: it does not match a line of Stock Transfer {transfer.name}. Use Receive Goods on the transfer to create the lines.")
        if key in seen:
            throw(f"Line {index}: that transfer line is listed twice.")
        seen.add(key)
        line.item_code, line.batch, line.serial_number, line.uom = original.item_code, original.batch, original.serial_number, original.uom
        line.outstanding_quantity = left[key]
        qty = _d(line.quantity)
        if qty <= 0:
            throw(f"Line {index}: Received Now must be greater than zero (delete the line to receive none of it).")
        if qty > left[key]:
            throw(f"Line {index}: {qty} received but only {left[key]} of {original.item_code} is still in transit.")
        if original.serial_number and qty != left[key]:
            throw(f"Line {index}: a serial-numbered item arrives whole.")


def record_receipt(doc) -> None:
    """After the stock has been posted: add what arrived to the transfer's lines and bring its status up to date."""
    lt = get_table("Stock Transfer Line")
    with db.transaction() as c:
        for line in doc.lines:
            row = c.execute(select(lt.c.received_quantity).where(lt.c.name == line.transfer_line)).first()
            c.execute(update(lt).where(lt.c.name == line.transfer_line).values(received_quantity=_d(row[0] if row else 0) + _d(line.quantity)))
    refresh_status(doc.stock_transfer)


def create_receipt(transfer_name: str, overrides: dict | None = None):
    """A draft receipt for everything still in transit (edit the quantities to receive part of it)."""
    transfer = get_doc("Stock Transfer", transfer_name, ignore_permissions=True)
    if int(transfer.docstatus or 0) != 1 or not transfer.transit_warehouse or transfer.transit_status == "Received":
        throw("This transfer has nothing in transit to receive.")
    left = outstanding(transfer)
    lines = [{"transfer_line": str(l.name), "item_code": l.item_code, "batch": l.batch, "serial_number": l.serial_number, "uom": l.uom,
              "outstanding_quantity": float(left[str(l.name)]), "quantity": float(left[str(l.name)])} for l in transfer.lines if left[str(l.name)] > 0]
    if not lines:
        throw("This transfer has nothing in transit to receive.")
    doc = new_doc("Stock Transfer Receipt", posting_date=date.today(), stock_transfer=transfer.name, transit_warehouse=transfer.transit_warehouse,
                  target_warehouse=transfer.target_warehouse, remarks=f"Receiving Stock Transfer {transfer.name}", lines=lines)
    return doc.insert()


def transit_rows(warehouse: str | None = None, as_of: date | None = None) -> list[dict]:
    """Goods still on the way, line by line, with how long they have been in transit."""
    from velora_erp.finance.inventory.controls import controls
    limit = int(controls()["transit_alert_days"])
    today = as_of or date.today()
    t, lt = get_table("Stock Transfer"), get_table("Stock Transfer Line")
    cond = [t.c.docstatus == 1, t.c.transit_warehouse.isnot(None), t.c.transit_status.in_(["In Transit", "Partially Received"])]
    if warehouse:
        cond.append((t.c.source_warehouse == warehouse) | (t.c.target_warehouse == warehouse) | (t.c.transit_warehouse == warehouse))
    with db.transaction() as c:
        rows = c.execute(select(t.c.name, t.c.posting_date, t.c.source_warehouse, t.c.transit_warehouse, t.c.target_warehouse, lt.c.item_code, lt.c.batch,
                                lt.c.quantity, lt.c.received_quantity).join(lt, (lt.c.parent == t.c.name) & (lt.c.parenttype == "Stock Transfer"))
                         .where(*cond).order_by(t.c.posting_date, t.c.name)).all()
    out = []
    for name, posted, src, via, dst, item, batch, sent, got in rows:
        left = _d(sent) - _d(got)
        if left <= 0:
            continue
        days = (today - posted).days
        out.append({"transfer": name, "posting_date": posted, "source_warehouse": src, "transit_warehouse": via, "target_warehouse": dst,
                    "item_code": item, "batch": batch, "sent": float(_d(sent)), "received": float(_d(got)), "in_transit": float(left),
                    "days_in_transit": days, "status": "Overdue" if days > limit else "On the way"})
    return out
