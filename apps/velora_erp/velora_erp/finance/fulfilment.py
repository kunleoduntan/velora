"""How far an order has been received, delivered and billed, the ERPNext way.

A follow-on document (Purchase Receipt, Purchase Invoice, Delivery Note, Sales Invoice) may take its lines from one source
document or from several: each line can carry its own `source_doctype` / `source_document` / `source_line`; a line without them
falls back to the document header. Quantities are counted line by line, so merging several orders into one receipt, or several
receipts into one invoice, is tracked exactly. The source order then shows Received %, Delivered % and Billed % and moves from
Open to Partially Processed to Completed on its own. Nothing here asks for approval: that is a workflow decision.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, func, select, update

from velora import db, get_doc, get_list, throw
from velora.db.tables import get_table

ZERO = Decimal("0")


def _d(value) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else 0))
    except Exception:  # noqa: BLE001 - a bad stored value counts as nothing
        return ZERO


def line_totals(target_doctype: str, source_doctype: str, source_name: str, *, statuses=(0, 1), exclude: str | None = None,
                where_parent: dict | None = None) -> dict[str, Decimal]:
    """Quantity already taken from each line of one source document, by that line's id (cancelled documents never count)."""
    parent, line = get_table(target_doctype), get_table(f"{target_doctype} Line")
    own = "source_document" in line.c and "source_doctype" in line.c                 # not every line table carries its own source
    src_doc = func.coalesce(func.nullif(line.c.source_document, ""), parent.c.source_document) if own else parent.c.source_document
    src_type = func.coalesce(func.nullif(line.c.source_doctype, ""), parent.c.source_doctype) if own else parent.c.source_doctype
    cond = [parent.c.docstatus.in_(list(statuses)), src_doc == source_name, src_type == source_doctype,
            line.c.source_line.isnot(None), line.c.source_line != ""]
    if exclude:
        cond.append(parent.c.name != exclude)
    for column, value in (where_parent or {}).items():
        cond.append(parent.c[column] == value)
    stmt = (select(line.c.source_line, func.sum(line.c.quantity)).select_from(line.join(parent, parent.c.name == line.c.parent))
            .where(and_(*cond)).group_by(line.c.source_line))
    with db.transaction() as conn:
        return {str(k): _d(v) for k, v in conn.execute(stmt).all()}


def matched_totals(source_receipt: str | None = None, *, statuses=(0, 1), exclude: str | None = None) -> dict[str, Decimal]:
    """Quantity of each Purchase Receipt line already matched on supplier invoices."""
    parent, line = get_table("Purchase Invoice"), get_table("Purchase Invoice Line")
    cond = [parent.c.docstatus.in_(list(statuses)), line.c.purchase_receipt_line.isnot(None), line.c.purchase_receipt_line != ""]
    if source_receipt:
        cond.append(line.c.purchase_receipt == source_receipt)
    if exclude:
        cond.append(parent.c.name != exclude)
    stmt = (select(line.c.purchase_receipt_line, func.sum(line.c.matched_quantity)).select_from(line.join(parent, parent.c.name == line.c.parent))
            .where(and_(*cond)).group_by(line.c.purchase_receipt_line))
    with db.transaction() as conn:
        return {str(k): _d(v) for k, v in conn.execute(stmt).all()}


def _stock_item(code) -> bool:
    from velora_erp.finance.inventory.ledger import is_stock_item
    return is_stock_item(code)


def _lines_by_id(doctype: str, name: str):
    return {str(l.name): l for l in (get_doc(doctype, name, ignore_permissions=True).lines or [])}


def _pct(done: Decimal, total: Decimal) -> Decimal:
    return Decimal("100") if total <= 0 else min(Decimal("100"), (done * 100 / total)).quantize(Decimal("0.01"))


def _write(doctype: str, name: str, **values):
    table = get_table(doctype)
    with db.transaction() as conn:
        conn.execute(update(table).where(table.c.name == name).values(**values))


def _status(current: str, received: Decimal, billed: Decimal, any_progress: bool) -> str:
    if current == "Closed":
        return current
    if received >= 100 and billed >= 100:
        return "Completed"
    return "Partially Processed" if any_progress else "Open"


def refresh_purchase_order(name: str) -> None:
    lines = _lines_by_id("Purchase Order", name)
    if not lines:
        return
    received = line_totals("Purchase Receipt", "Purchase Order", name, statuses=(1,))
    # an invoice that receives the goods itself (Update Stock) counts as received too
    received_by_invoice = line_totals("Purchase Invoice", "Purchase Order", name, statuses=(1,), where_parent={"update_stock": 1})
    billed = line_totals("Purchase Invoice", "Purchase Order", name, statuses=(1,))
    # goods received on a receipt of this order and then invoiced through that receipt
    via_receipt = matched_totals()
    if via_receipt:
        parent, line = get_table("Purchase Receipt"), get_table("Purchase Receipt Line")
        src_doc = func.coalesce(func.nullif(line.c.source_document, ""), parent.c.source_document)
        src_type = func.coalesce(func.nullif(line.c.source_doctype, ""), parent.c.source_doctype)
        with db.transaction() as conn:
            rows = conn.execute(select(line.c.name, line.c.source_line).select_from(line.join(parent, parent.c.name == line.c.parent))
                                .where(and_(parent.c.docstatus == 1, src_doc == name, src_type == "Purchase Order"))).all()
        for receipt_line, po_line in rows:
            if po_line:
                billed[str(po_line)] = billed.get(str(po_line), ZERO) + via_receipt.get(str(receipt_line), ZERO)
    stock_total = stock_done = all_total = all_done = ZERO
    for key, row in lines.items():
        qty = _d(row.quantity)
        all_total += qty
        all_done += min(qty, billed.get(key, ZERO))
        got = received.get(key, ZERO) + received_by_invoice.get(key, ZERO)
        if got > 0 or _stock_item(row.item_code):                  # services have nothing to receive unless someone receives them
            stock_total += qty
            stock_done += min(qty, got)
    per_received, per_billed = _pct(stock_done, stock_total), _pct(all_done, all_total)
    current = get_doc("Purchase Order", name, ignore_permissions=True).document_status
    progress = (stock_done > 0) or (all_done > 0)
    _write("Purchase Order", name, per_received=per_received, per_billed=per_billed,
           document_status=_status(current, per_received, per_billed, progress))


def refresh_sales_order(name: str) -> None:
    lines = _lines_by_id("Sales Order", name)
    if not lines:
        return
    delivered = line_totals("Delivery Note", "Sales Order", name, statuses=(1,))
    billed = line_totals("Sales Invoice", "Sales Order", name, statuses=(1,))
    stock_total = stock_done = all_total = all_done = ZERO
    for key, row in lines.items():
        qty = _d(row.quantity)
        all_total += qty
        all_done += min(qty, billed.get(key, ZERO))
        if delivered.get(key, ZERO) > 0 or _stock_item(row.item_code):
            stock_total += qty
            stock_done += min(qty, delivered.get(key, ZERO))
    per_delivered, per_billed = _pct(stock_done, stock_total), _pct(all_done, all_total)
    current = get_doc("Sales Order", name, ignore_permissions=True).document_status
    _write("Sales Order", name, per_delivered=per_delivered, per_billed=per_billed,
           document_status=_status(current, per_delivered, per_billed, stock_done > 0 or all_done > 0))


def refresh_purchase_receipt(name: str) -> None:
    lines = _lines_by_id("Purchase Receipt", name)
    matched = matched_totals(name, statuses=(1,))
    total = sum((_d(l.quantity) for l in lines.values()), ZERO)
    done = sum((min(_d(l.quantity), matched.get(k, ZERO)) for k, l in lines.items()), ZERO)
    _write("Purchase Receipt", name, per_billed=_pct(done, total))


def refresh_delivery_note(name: str) -> None:
    header = get_doc("Delivery Note", name, ignore_permissions=True)
    lines = {str(l.name): l for l in header.lines or []}
    billed = line_totals("Sales Invoice", "Delivery Note", name, statuses=(1,))
    # goods invoiced through the Sales Order they came from count as billed too
    by_order: dict[str, dict[str, Decimal]] = {}
    for key, line in lines.items():
        so = getattr(line, "source_document", None) or header.source_document
        so_line = str(getattr(line, "source_line", "") or "")
        if so_line and so and (getattr(line, "source_doctype", None) or header.source_doctype) == "Sales Order" and key not in billed:
            if so not in by_order:
                by_order[so] = line_totals("Sales Invoice", "Sales Order", so, statuses=(1,))
            billed[key] = min(_d(line.quantity), by_order[so].get(so_line, ZERO))
    total = sum((_d(l.quantity) for l in lines.values()), ZERO)
    done = sum((min(_d(l.quantity), billed.get(k, ZERO)) for k, l in lines.items()), ZERO)
    _write("Delivery Note", name, per_billed=_pct(done, total))


REFRESH = {"Purchase Order": refresh_purchase_order, "Sales Order": refresh_sales_order, "Purchase Receipt": refresh_purchase_receipt,
           "Delivery Note": refresh_delivery_note}


def sources_of(doc) -> list[tuple[str, str]]:
    """Every document this one draws from (header and each line), receipts before the orders behind them."""
    found: dict[tuple[str, str], None] = {}
    if getattr(doc, "source_doctype", None) and getattr(doc, "source_document", None):
        found[(doc.source_doctype, doc.source_document)] = None
    for line in doc.lines or []:
        if getattr(line, "source_doctype", None) and getattr(line, "source_document", None):
            found[(line.source_doctype, line.source_document)] = None
        if getattr(line, "purchase_receipt", None):
            found[("Purchase Receipt", line.purchase_receipt)] = None
    ordered = sorted(found, key=lambda k: 0 if k[0] in ("Purchase Receipt", "Delivery Note") else 1)
    extra = []
    for doctype, name in ordered:                       # a receipt or delivery that came from an order moves that order too
        if doctype in ("Purchase Receipt", "Delivery Note"):
            parent = get_doc(doctype, name, ignore_permissions=True)
            if parent.source_doctype and parent.source_document:
                extra.append((parent.source_doctype, parent.source_document))
            for line in parent.lines or []:
                if getattr(line, "source_doctype", None) and getattr(line, "source_document", None):
                    extra.append((line.source_doctype, line.source_document))
    return ordered + [e for e in dict.fromkeys(extra) if e not in found]


def refresh_for(doc) -> None:
    """Call after a follow-on document is submitted: bring every source's percentages and status up to date."""
    for doctype, name in sources_of(doc):
        fn = REFRESH.get(doctype)
        if fn:
            fn(name)
    if doc.doctype in REFRESH and doc.doctype in ("Purchase Receipt", "Delivery Note"):
        REFRESH[doc.doctype](doc.name)


# ---------------------------------------------------------------------------------------------------------------- checks
def check_not_over_billed(doc, *, source_doctype: str) -> None:
    """An invoice may not bill more of an order line than the order asked for (counting every other live invoice)."""
    wanted: dict[tuple[str, str], Decimal] = {}
    for line in doc.lines or []:
        key = str(getattr(line, "source_line", "") or "")
        src = getattr(line, "source_document", None) or getattr(doc, "source_document", None)
        stype = getattr(line, "source_doctype", None) or getattr(doc, "source_doctype", None)
        if key and src and stype == source_doctype:
            wanted[(src, key)] = wanted.get((src, key), ZERO) + _d(line.quantity)
    for src in {s for s, _ in wanted}:
        order = _lines_by_id(source_doctype, src)
        taken = line_totals(doc.doctype, source_doctype, src, exclude=doc.name)
        for (s, key), qty in wanted.items():
            if s != src:
                continue
            original = order.get(key)
            if original is None:
                throw(f"{source_doctype} {src} has no line {key}.")
            allowed = _d(original.quantity)
            if taken.get(key, ZERO) + qty > allowed:
                throw(f"{original.item_code or 'Line'}: billing {taken.get(key, ZERO) + qty} would exceed the {allowed} on {source_doctype} {src}.")


def validate_sales_sources(doc) -> None:
    """Sales Invoice lines that name their own source (Sales Order or Delivery Note) must match it; other lines are free."""
    cache: dict[tuple[str, str], dict] = {}
    for index, line in enumerate(doc.lines or [], 1):
        key = str(getattr(line, "source_line", "") or "")
        if not key:
            continue
        stype = getattr(line, "source_doctype", None) or getattr(doc, "source_doctype", None)
        sname = getattr(line, "source_document", None) or getattr(doc, "source_document", None)
        if stype not in ("Sales Order", "Delivery Note") or not sname:
            throw(f"Invoice line {index}: its source must be a submitted Sales Order or Delivery Note.")
        if (stype, sname) not in cache:
            source = get_doc(stype, sname)
            if int(source.docstatus or 0) != 1 or source.party != doc.party:
                throw(f"{stype} {sname} must be submitted and belong to the same customer.")
            if (doc.currency or "").upper() != (source.currency or "").upper():
                throw(f"Invoice currency must match {stype} {sname}.")
            cache[(stype, sname)] = {str(l.name): l for l in source.lines or []}
        original = cache[(stype, sname)].get(key)
        if original is None:
            throw(f"Invoice line {index}: source line does not belong to {stype} {sname}.")
        if getattr(line, "item_code", None) != getattr(original, "item_code", None):
            throw(f"Invoice line {index}: Item Code cannot differ from its source {stype} line.")
        if _d(getattr(line, "quantity", 0)) <= 0:
            throw(f"Invoice line {index}: invoiced quantity must be positive.")
    # stock goods on an order may be billed only once delivered
    from velora_erp.finance.document_flow.sales_invoicing import _is_stock_item
    wanted: dict[tuple[str, str], Decimal] = {}
    for line in doc.lines or []:
        stype = getattr(line, "source_doctype", None) or getattr(doc, "source_doctype", None)
        sname = getattr(line, "source_document", None) or getattr(doc, "source_document", None)
        key = str(getattr(line, "source_line", "") or "")
        if key and stype == "Sales Order" and sname and _is_stock_item(getattr(line, "item_code", None)):
            wanted[(sname, key)] = wanted.get((sname, key), ZERO) + _d(line.quantity)
    for sname in {s for s, _ in wanted}:
        billed = line_totals("Sales Invoice", "Sales Order", sname, exclude=getattr(doc, "name", None))
        delivered = line_totals("Delivery Note", "Sales Order", sname, statuses=(1,))
        for (s, key), qty in wanted.items():
            if s == sname and billed.get(key, ZERO) + qty > delivered.get(key, ZERO):
                throw(f"Sales Order {sname}: billing {billed.get(key, ZERO) + qty} would exceed the {delivered.get(key, ZERO)} delivered so far.")
