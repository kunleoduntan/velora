"""Get Items From: fill a draft Purchase Receipt, Purchase Invoice, Delivery Note or Sales Invoice from open orders, receipts or deliveries.

ERPNext's "Get Items From" button. The person picks one or several source documents of the same party; this module works out what is
still open on each and returns ready-made lines (each remembering where it came from) for the form to add. Nothing is saved here:
the draft document is saved by the person, and the fulfilment of the sources updates when it is submitted.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from velora import db, get_doc, get_list, throw

from velora_erp.finance.fulfilment import ZERO, _d, line_totals, matched_totals

CENT = Decimal("0.01")
# target -> the documents it can take items from
SOURCES = {
    "Purchase Receipt": ("Purchase Order",),
    "Purchase Invoice": ("Purchase Order", "Purchase Receipt"),
    "Delivery Note": ("Sales Order",),
    "Sales Invoice": ("Sales Order", "Delivery Note"),
}
PARTY_FIELD = {"Purchase Order": "supplier_name", "Purchase Receipt": "supplier_name", "Sales Order": "customer_name", "Delivery Note": "customer_name"}


def sources_for(target: str) -> list[str]:
    return list(SOURCES.get(target, ()))


def _check(target: str, source: str) -> None:
    if source not in SOURCES.get(target, ()):
        throw(f"{target} cannot take items from {source}.")


def _item(code):
    if code and db.exists("Inventory Item", code):
        return get_doc("Inventory Item", code, ignore_permissions=True)
    return None


def _is_stock(code) -> bool:
    item = _item(code)
    return bool(item and item.is_stock_item and not item.disabled)


def _net(rate, pct, disc, qty) -> Decimal:
    net = _d(rate) * (Decimal("1") - _d(pct) / Decimal("100")) - _d(disc)
    return (net * qty).quantize(CENT, rounding=ROUND_HALF_UP)


def _open_lines(target: str, source: str, doc, exclude: str | None) -> list[dict]:
    """The lines of one source document that can still be taken, with the open quantity of each."""
    out = []
    if (target, source) == ("Purchase Invoice", "Purchase Receipt"):
        matched = matched_totals(doc.name, exclude=exclude)
        for line in doc.lines or []:
            left = _d(line.quantity) - matched.get(str(line.name), ZERO)
            if left > 0:
                out.append({"line": line, "open": left})
        return out
    taken = line_totals(target, source, doc.name, exclude=exclude)
    if target == "Purchase Invoice":                                   # goods already on a receipt are invoiced from that receipt
        received = line_totals("Purchase Receipt", "Purchase Order", doc.name)
    elif target == "Sales Invoice" and source == "Sales Order":        # stock goods are billed once delivered
        delivered = line_totals("Delivery Note", "Sales Order", doc.name, statuses=(1,))
    for line in doc.lines or []:
        key = str(line.name)
        left = _d(line.quantity) - taken.get(key, ZERO)
        if target == "Purchase Invoice" and _is_stock(line.item_code):
            left -= received.get(key, ZERO)
        if target == "Sales Invoice" and source == "Sales Order" and _is_stock(line.item_code):
            left = min(left, delivered.get(key, ZERO) - taken.get(key, ZERO))
        if left > 0:
            out.append({"line": line, "open": left})
    return out


def candidates(target: str, source: str, party: str | None = None, txt: str = "", exclude: str | None = None, limit: int = 50) -> list[dict]:
    """Submitted source documents that still have something to take, newest first."""
    _check(target, source)
    filters = [["docstatus", "=", 1]]
    if party:
        filters.append(["party", "=", party])
    if txt:
        filters.append(["_search", "like", txt])
    rows = get_list(source, filters=filters, fields=["name", "party", "document_date", "currency", "document_status", PARTY_FIELD[source]],
                    order_by="modified desc", limit=limit * 3)
    out = []
    for row in rows:
        if row.get("document_status") == "Closed":
            continue
        doc = get_doc(source, row["name"])
        open_lines = _open_lines(target, source, doc, exclude)
        if not open_lines:
            continue
        out.append({"name": row["name"], "party": row["party"], "party_name": row.get(PARTY_FIELD[source]) or "",
                    "date": str(row.get("document_date") or ""), "currency": row["currency"],
                    "open_lines": len(open_lines), "open_quantity": str(sum((x["open"] for x in open_lines), ZERO))})
        if len(out) >= limit:
            break
    return out


def _line(target: str, source: str, doc, entry: dict) -> dict:
    src, qty = entry["line"], entry["open"]
    base = {"source_doctype": source, "source_document": doc.name, "source_line": str(src.name), "item_code": src.item_code,
            "item_name": getattr(src, "item_name", None), "description": getattr(src, "description", None) or src.item_code,
            "quantity": qty, "uom": getattr(src, "uom", None), "conversion_factor": getattr(src, "conversion_factor", 1) or 1}
    rate = getattr(src, "rate", None)
    if target == "Purchase Receipt":
        base.update({"valuation_rate": _d(rate if rate is not None else getattr(src, "valuation_rate", 0)),
                     "batch": getattr(src, "batch", None), "serial_number": getattr(src, "serial_number", None)})
    elif target == "Delivery Note":
        base.update({"rate": _d(rate), "discount_percentage": getattr(src, "discount_percentage", 0) or 0,
                     "discount_amount": getattr(src, "discount_amount", 0) or 0, "price_basis": getattr(src, "price_basis", None) or "Automatic",
                     "cost_rate": getattr(src, "cost_rate", None), "cost_source": getattr(src, "cost_source", None),
                     "batch": getattr(src, "batch", None), "serial_number": getattr(src, "serial_number", None)})
    elif target == "Purchase Invoice" and source == "Purchase Order":
        item = _item(src.item_code)
        pct, disc = getattr(src, "discount_percentage", 0) or 0, getattr(src, "discount_amount", 0) or 0
        base.update({"rate": _d(rate), "discount_percentage": pct, "discount_amount": disc, "amount": _net(rate, pct, disc, qty),
                     "account": getattr(item, "expense_account", None) if item else None, "cost_centre": getattr(src, "cost_centre", None),
                     "warehouse": getattr(src, "warehouse", None)})
    elif target == "Purchase Invoice":                                  # from a Purchase Receipt: matched against the goods received
        cost = _d(getattr(src, "valuation_rate", 0))
        base = {"item_code": src.item_code, "item_name": getattr(src, "item_name", None), "description": base["description"], "quantity": qty,
                "uom": base["uom"], "conversion_factor": base["conversion_factor"], "purchase_receipt": doc.name,
                "purchase_receipt_line": str(src.name), "matched_quantity": qty, "rate": cost, "valuation_rate": cost,
                "amount": (qty * cost).quantize(CENT, rounding=ROUND_HALF_UP), "batch": getattr(src, "batch", None),
                "serial_number": getattr(src, "serial_number", None)}
    elif target == "Sales Invoice" and source == "Sales Order":
        pct, disc = _d(getattr(src, "discount_percentage", 0)), _d(getattr(src, "discount_amount", 0))
        amount = _net(rate, pct, disc, qty)
        tax_rate = _d(getattr(src, "tax_rate", 0))
        base.update({"account": getattr(src, "revenue_account", None), "rate": _d(rate), "discount_percentage": pct, "discount_amount": disc,
                     "amount": amount, "tax_account": getattr(src, "tax_account", None), "tax_code": getattr(src, "tax_code", None),
                     "tax_rate": tax_rate, "tax_amount": (amount * tax_rate / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP),
                     "cost_rate": getattr(src, "cost_rate", 0), "cost_source": getattr(src, "cost_source", None),
                     "cost_centre": getattr(src, "cost_centre", None)})
    return base


def pull(target: str, source: str, names: list[str], party: str | None = None, exclude: str | None = None) -> dict:
    """Lines (and the header values they imply) for the chosen source documents."""
    _check(target, source)
    names = [str(n) for n in dict.fromkeys(names or []) if n]
    if not names:
        throw("Select at least one document.")
    docs = [get_doc(source, n) for n in names]
    parties = {d.party for d in docs} | ({party} if party else set())
    if len(parties) > 1:
        throw("All the documents must belong to the same " + ("customer." if source in ("Sales Order", "Delivery Note") else "supplier."))
    currencies = {(d.currency or "").upper() for d in docs}
    if len(currencies) > 1:
        throw("All the documents must use the same currency.")
    lines = []
    for doc in docs:
        if int(doc.docstatus or 0) != 1:
            throw(f"{source} {doc.name} must be submitted first.")
        if getattr(doc, "document_status", None) == "Closed":
            throw(f"{source} {doc.name} is closed.")
        if (target, source) == ("Sales Invoice", "Delivery Note"):
            from .more_flows import delivery_invoice_lines
            lines += delivery_invoice_lines(doc)
        else:
            lines += [_line(target, source, doc, e) for e in _open_lines(target, source, doc, exclude)]
    if not lines:
        throw("Nothing is left to take from the selected documents.")
    first = docs[0]
    header = {"party": first.party, "currency": first.currency, "exchange_rate": first.exchange_rate}
    if target == "Purchase Receipt":
        header["warehouse"] = next((getattr(l, "warehouse", None) for d in docs for l in d.lines or [] if getattr(l, "warehouse", None)), None)
    if target == "Purchase Invoice" and source == "Purchase Order":
        stock = any(_is_stock(l.get("item_code")) for l in lines)
        warehouse = next((l.get("warehouse") for l in lines if l.get("warehouse")), None)
        if stock and warehouse:
            header.update({"update_stock": 1, "warehouse": warehouse})
    return {"header": header, "lines": [{k: (str(v) if isinstance(v, Decimal) else v) for k, v in l.items() if v is not None} for l in lines]}
