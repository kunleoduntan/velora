"""Validation for non-posting sales, purchasing and logistics documents."""
from decimal import Decimal, InvalidOperation
from velora import get_doc, throw


def _decimal(value, label):
    try:
        result = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        throw(f"{label} must be numeric.")
    if not result.is_finite():
        throw(f"{label} must be finite.")
    return result


def validate_lines(doc, *, require_rate=False):
    if not doc.lines:
        throw("At least one document line is required.")
    for index, line in enumerate(doc.lines, 1):
        description = str(getattr(line, "description", "") or "").strip()
        if not description and getattr(line, "item_code", None):
            from velora import db
            if db.exists("Inventory Item", line.item_code):               # like ERPNext, the item supplies the description
                item = get_doc("Inventory Item", line.item_code, ignore_permissions=True)
                description = str(getattr(item, "description", None) or getattr(item, "item_name", None) or line.item_code).strip()
                line.description = description
        if not description:
            throw(f"Line {index}: Description is required.")
        quantity = _decimal(getattr(line, "quantity", 0), f"Line {index} Quantity")
        if quantity <= 0:
            throw(f"Line {index}: Quantity must be greater than zero.")
        if require_rate:
            rate = _decimal(getattr(line, "rate", 0), f"Line {index} Rate")
            if rate < 0:
                throw(f"Line {index}: Rate cannot be negative.")
            discount_pct = _decimal(getattr(line, "discount_percentage", 0), f"Line {index} Discount Percentage")
            discount_amount = _decimal(getattr(line, "discount_amount", 0), f"Line {index} Discount Amount")
            if discount_pct < 0 or discount_pct >= 100 or discount_amount < 0:
                throw(f"Line {index}: Discounts must be non-negative and percentage discounts must be below 100%.")
            net_rate = rate * (Decimal("1") - discount_pct / Decimal("100")) - discount_amount
            if net_rate < 0:
                throw(f"Line {index}: Discounts cannot reduce the unit selling rate below zero.")
            line.amount = net_rate * quantity


def validate_order(doc, party_type):
    if not doc.document_date or not doc.party:
        throw("Document Date and party are required.")
    party = get_doc(party_type, doc.party)
    if getattr(party, "disabled", 0):
        throw(f"Select an active {party_type}.")
    if not doc.currency or len(str(doc.currency)) != 3:
        throw("Currency must be a three-letter ISO code.")
    from velora_erp.finance.multicurrency import resolve_exchange_rate, apply_base_amounts
    resolve_exchange_rate(doc, "document_date")
    rate = _decimal(doc.exchange_rate, "Exchange Rate")
    if rate <= 0:
        throw("Exchange Rate must be greater than zero.")
    validate_lines(doc, require_rate=True)
    total = sum((_decimal(getattr(l, "amount", 0), "Line amount") for l in doc.lines), Decimal("0"))
    if hasattr(doc, "total_amount"):
        doc.total_amount = total
    if hasattr(doc, "grand_total"):
        tax = sum((_decimal(getattr(l, "amount", 0), "Line amount") * _decimal(getattr(l, "tax_rate", 0), "Tax rate") / Decimal("100") for l in doc.lines if getattr(l, "tax_account", None)), Decimal("0")).quantize(Decimal("0.01"))
        doc.tax_amount = tax; doc.grand_total = total + tax
    if hasattr(doc, "base_total_amount"):
        doc.base_total_amount = (total * rate).quantize(Decimal("0.01"))
    apply_base_amounts(doc)
    if doc.source_document and not doc.source_doctype:
        throw("Source Document Type is required when Source Document is supplied.")


def _line_source(doc, line, source_doctype):
    """The order a line draws from: its own source if it has one, otherwise the document header's."""
    stype = getattr(line, "source_doctype", None) or getattr(doc, "source_doctype", None)
    sname = getattr(line, "source_document", None) or getattr(doc, "source_document", None)
    return stype, sname


def validate_fulfilment(doc, source_doctype, party_type):
    """A receipt or delivery may stand alone, or draw its lines from one or several submitted orders (ERPNext's Get Items From)."""
    if not doc.document_date or not doc.party:
        throw("Document Date and party are required.")
    cache = {}
    for index, line in enumerate(doc.lines or [], 1):
        source_line_id = str(getattr(line, "source_line", "") or "")
        if not source_line_id:
            continue                                                          # a line typed in by hand needs no order
        stype, sname = _line_source(doc, line, source_doctype)
        if stype != source_doctype or not sname:
            throw(f"Line {index}: its source must be a submitted {source_doctype}.")
        if sname not in cache:
            source = get_doc(source_doctype, sname)
            if int(source.docstatus or 0) != 1:
                throw(f"Source {source_doctype} {sname} must be submitted.")
            if source.party != doc.party:
                throw(f"{party_type} must match the source {source_doctype} {sname}.")
            cache[sname] = {str(getattr(l, "name", "")): l for l in source.lines or []}
        original = cache[sname].get(source_line_id)
        if not original:
            throw(f"Line {index}: select a valid source line from {source_doctype} {sname}.")
        if getattr(line, "item_code", None) != getattr(original, "item_code", None):
            throw(f"Line {index}: Item Code cannot differ from its source {source_doctype} line.")
        if (getattr(line, "uom", None) or None) != (getattr(original, "uom", None) or None):
            throw(f"Line {index}: Unit of Measure must match its source {source_doctype} line.")
        source_factor = _decimal(getattr(original, "conversion_factor", 1) or 1, "Source conversion factor")
        target_factor = _decimal(getattr(line, "conversion_factor", 1) or 1, "Target conversion factor")
        if source_factor != target_factor:
            throw(f"Line {index}: Stock UOM Conversion Factor must match its source {source_doctype} line.")
    validate_lines(doc)
    check_not_over_fulfilled(doc, source_doctype, cache)


def check_not_over_fulfilled(doc, source_doctype, source_lines=None):
    """Delivered or received quantity, across every submitted document of this kind, may not exceed what the order asked for."""
    from velora_erp.finance.fulfilment import line_totals
    wanted = {}
    for line in doc.lines or []:
        key = str(getattr(line, "source_line", "") or "")
        stype, sname = _line_source(doc, line, source_doctype)
        if key and sname and stype == source_doctype:
            wanted[(sname, key)] = wanted.get((sname, key), Decimal("0")) + _decimal(getattr(line, "quantity", 0), "Quantity")
    verb = {"Delivery Note": "delivered", "Sales Order": "ordered"}.get(doc.doctype, "received")
    for sname in {s for s, _ in wanted}:
        lines = (source_lines or {}).get(sname)
        if lines is None:
            lines = {str(getattr(l, "name", "")): l for l in get_doc(source_doctype, sname).lines or []}
        done = line_totals(doc.doctype, source_doctype, sname, statuses=(1,), exclude=doc.name)
        for (s, key), qty in wanted.items():
            if s != sname:
                continue
            ordered = _decimal(getattr(lines[key], "quantity", 0), "Ordered quantity")
            if done.get(key, Decimal("0")) + qty > ordered:
                throw(f"{getattr(lines[key], 'item_code', None) or 'Line'}: {verb} quantity {done.get(key, Decimal('0')) + qty} would exceed the {ordered} ordered on {source_doctype} {sname}.")


def validate_waybill(doc):
    if not doc.delivery_note:
        throw("A Delivery Note is required for a Waybill.")
    if not doc.document_date or not doc.party:
        throw("Waybill Date and Customer are required.")
    validate_lines(doc)
