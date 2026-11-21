"""Take a cancelled document's stock out of the Stock Ledger.

* Every Stock Ledger Record the document wrote is deleted (a copy goes into the Posting Cancellation Log).
* The running balance on every LATER record of the same item / warehouse / batch / serial is worked out again, so quantity-after,
  value-after and valuation rate stay true. Balances themselves always come from the sum of the records, so they are right at once.
* If taking the stock out would leave any later record with a negative quantity, the cancel is refused and names the later
  documents that still need that stock ("cancel those first"). Nothing is changed.
* Serial numbers go back to where the remaining ledger says they are; reservations an issue used up are given back.

What is NOT done: the cost of issues that were already made is not recalculated. A moving-average or FIFO issue posted after a
cancelled receipt keeps the cost it was posted at; the stock value and the Inventory account still agree, because both move by the
exact amounts that were posted. (ERPNext re-posts those issues; this is the one place Velora is deliberately simpler.)
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select, update

from velora import db, get_doc, throw
from velora.db.tables import get_table

ZERO = Decimal("0")


def _d(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def _order(row):
    return (str(row["posting_date"] or ""), str(row["creation"] or ""), str(row["name"] or ""))


def _resequence(key, removed_voucher: str) -> None:
    """Recompute quantity-after / value-after / rate on the records of one stock key; refuse if any quantity goes below zero."""
    item, warehouse, batch, serial = key
    t = get_table("Stock Ledger Record")
    with db.transaction() as conn:
        rows = sorted((dict(r) for r in conn.execute(select(t).where(
            t.c.item_code == item, t.c.warehouse == warehouse, t.c.batch == batch, t.c.serial_number == serial)).mappings()), key=_order)
        qty = value = ZERO
        for r in rows:
            qty += _d(r["actual_qty"])
            value += _d(r["stock_value_difference"])
            if qty < 0:
                later = sorted({x["voucher_no"] for x in rows if _order(x) >= _order(r) and x["voucher_type"] and x["actual_qty"] and _d(x["actual_qty"]) < 0})
                throw(f"{removed_voucher} cannot be cancelled: {item} in {warehouse} would be short by {abs(qty)} on {r['posting_date']}. "
                      f"Documents that already used this stock: {', '.join(later[:5]) or r['voucher_no']}. Cancel those first.")
            rate = (value / qty) if qty > 0 else _d(r["valuation_rate"])
            if (_d(r["qty_after_transaction"]), _d(r["stock_value_after_transaction"])) != (qty, value) or _d(r["valuation_rate"]) != rate:
                conn.execute(update(t).where(t.c.name == r["name"]).values(
                    qty_after_transaction=qty, stock_value_after_transaction=value, valuation_rate=rate))


def _restore_serials(serials: set[str]) -> None:
    t = get_table("Stock Ledger Record")
    for serial in serials:
        if not db.exists("Serial Number", serial):
            continue
        with db.transaction() as conn:
            rows = sorted((dict(r) for r in conn.execute(select(t).where(t.c.serial_number == serial)).mappings()), key=_order)
        doc = get_doc("Serial Number", serial, ignore_permissions=True)
        held: dict[str, Decimal] = {}
        for r in rows:
            held[r["warehouse"]] = held.get(r["warehouse"], ZERO) + _d(r["actual_qty"])
        where = next((w for w, q in held.items() if q > 0), None)
        if where:
            doc.status, doc.warehouse = "Available", where
        else:
            last = rows[-1]["voucher_type"] if rows else None
            doc.status = "Returned" if last == "Purchase Return" else "Scrapped" if (last in ("Stock Reconciliation", None) or not rows) else "Delivered"
            doc.warehouse = None
        doc.save(ignore_permissions=True)


def _give_back_reservations(doc, issued: dict[tuple[str, str], Decimal]) -> None:
    """Stock the issue used from a reservation is reserved again."""
    from velora_erp.finance.inventory import reservations
    refs = reservations._refs(doc)
    t = get_table("Stock Reservation")
    with db.transaction() as c:
        for (item, warehouse), qty in issued.items():
            left = qty
            rows = c.execute(select(t).where(t.c.item_code == item, t.c.warehouse == warehouse, t.c.consumed_quantity > 0)).mappings().all()
            for r in rows:
                if left <= 0:
                    break
                if (r["reserved_for_doctype"], r["reserved_for"]) not in refs:
                    continue
                give = min(left, _d(r["consumed_quantity"]))
                c.execute(update(t).where(t.c.name == r["name"]).values(
                    consumed_quantity=_d(r["consumed_quantity"]) - give, status="Active" if r["status"] == "Fulfilled" else r["status"]))
                left -= give


def remove_stock(doc, report) -> None:
    from velora_erp.finance.inventory.ledger import assert_period_open
    t = get_table("Stock Ledger Record")
    with db.transaction() as conn:
        rows = [dict(r) for r in conn.execute(select(t).where(t.c.voucher_type == doc.doctype, t.c.voucher_no == doc.name)).mappings()]
    if not rows:
        _after(doc, report)
        return
    for r in rows:
        assert_period_open(r["item_code"], r["warehouse"], r["posting_date"])
    keys = {(r["item_code"], r["warehouse"], r["batch"], r["serial_number"]) for r in rows}
    serials = {r["serial_number"] for r in rows if r["serial_number"]}
    issued: dict[tuple[str, str], Decimal] = {}
    for r in rows:
        if _d(r["actual_qty"]) < 0:
            k = (r["item_code"], r["warehouse"])
            issued[k] = issued.get(k, ZERO) + abs(_d(r["actual_qty"]))
    report.snapshot["stock_ledger"] = [{k: (str(v) if v is not None else None) for k, v in r.items()} for r in rows]
    report.stock_rows += len(rows)
    with db.transaction() as conn:
        conn.execute(delete(t).where(t.c.voucher_type == doc.doctype, t.c.voucher_no == doc.name))
    for key in sorted(keys, key=str):
        _resequence(key, f"{doc.doctype} {doc.name}")
    _restore_serials(serials)
    if issued:
        _give_back_reservations(doc, issued)
    report.note(f"{len(rows)} stock ledger rows removed")
    _after(doc, report)


def _after(doc, report) -> None:
    """Things that were worked out from the stock the document moved."""
    if doc.doctype == "Stock Transfer Receipt":
        lt = get_table("Stock Transfer Line")
        from velora_erp.finance.inventory import transit
        with db.transaction() as c:
            for line in doc.lines:
                row = c.execute(select(lt.c.received_quantity).where(lt.c.name == line.transfer_line)).first()
                c.execute(update(lt).where(lt.c.name == line.transfer_line).values(received_quantity=max(ZERO, _d(row[0] if row else 0) - _d(line.quantity))))
        transit.refresh_status(doc.stock_transfer)
        report.note(f"Stock Transfer {doc.stock_transfer} shows the goods as still in transit")
    if doc.doctype == "Stock Entry" and getattr(doc, "material_request", None):
        from velora_erp.finance.inventory.requests import refresh_fulfilment
        refresh_fulfilment(doc.material_request)
    receipt = None
    if doc.doctype == "Purchase Receipt":
        receipt = doc
    elif doc.doctype == "Landed Cost Voucher" and getattr(doc, "purchase_receipt", None):
        receipt = get_doc("Purchase Receipt", doc.purchase_receipt, ignore_permissions=True)
    if receipt is not None:
        from velora_erp.finance.pricing import refresh_last_purchase_cost
        for item_code in {getattr(line, "item_code", None) for line in receipt.lines or [] if getattr(line, "item_code", None)}:
            refresh_last_purchase_cost(item_code)
