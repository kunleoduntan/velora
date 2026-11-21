"""Further sales and purchase conversions: invoice from Delivery Note, Waybill or Quotation; Purchase Invoice from Purchase Order."""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from velora import db, get_doc, get_list, new_doc, throw

CENT = Decimal("0.01")
INVOICE_OVERRIDES = {"invoice_date", "posting_date", "due_date", "party_reference", "narration"}


def _d(v):
    return Decimal(str(v if v not in (None, "") else 0))


def _check_overrides(overrides, extra=()):
    bad = set(overrides) - INVOICE_OVERRIDES - set(extra)
    if bad:
        throw("Unsupported Create From override(s): " + ", ".join(sorted(bad)))


def _item(code):
    if code and db.exists("Inventory Item", code):
        return get_doc("Inventory Item", code, ignore_permissions=True)
    return None


def _net_amount(rate, pct, disc, qty):
    net = _d(rate) * (Decimal("1") - _d(pct) / Decimal("100")) - _d(disc)
    return (net * qty).quantize(CENT, rounding=ROUND_HALF_UP)


def create_sales_invoice_from_delivery(dn_name, overrides=None):
    """Bill what one Delivery Note delivered.

    A delivery that came from a single Sales Order is billed through that order (quantity caps and credit control unchanged).
    A delivery typed in by hand, or one that merged several orders, is billed line by line from its own rates."""
    from .sales_invoicing import create_sales_invoice_from_order
    overrides = dict(overrides or {}); _check_overrides(overrides)
    dn = get_doc("Delivery Note", dn_name)
    if int(dn.docstatus or 0) != 1:
        throw("Only a submitted Delivery Note can be invoiced.")
    sources = {(getattr(l, "source_document", None) or dn.source_document) for l in dn.lines or [] if getattr(l, "source_line", None)}
    pure = (dn.source_doctype == "Sales Order" and dn.source_document and sources == {dn.source_document}
            and all(getattr(l, "source_line", None) for l in dn.lines or []))
    if pure:
        only = {}
        for line in dn.lines or []:
            key = str(getattr(line, "source_line", "") or "")
            only[key] = only.get(key, Decimal("0")) + _d(line.quantity)
        overrides.setdefault("narration", f"Sales Invoice created from Delivery Note {dn.name} (Sales Order {dn.source_document})")
        return create_sales_invoice_from_order(dn.source_document, overrides=overrides, only=only)
    return _invoice_from_delivery_lines(dn, overrides)


def delivery_invoice_lines(dn) -> list[dict]:
    """Invoice lines for the part of a Delivery Note that has not been billed yet (each carries its own source)."""
    from velora_erp.finance.fulfilment import line_totals
    already = line_totals("Sales Invoice", "Delivery Note", dn.name)
    orders, order_billed = {}, {}
    lines = []
    for line in dn.lines or []:
        key = str(line.name)
        so, so_line = (getattr(line, "source_document", None) or dn.source_document), str(getattr(line, "source_line", "") or "")
        from_order = bool(so_line and (getattr(line, "source_doctype", None) or dn.source_doctype) == "Sales Order" and so)
        original = None
        if from_order:
            if so not in orders:
                orders[so] = {str(l.name): l for l in get_doc("Sales Order", so, ignore_permissions=True).lines or []}
                order_billed[so] = line_totals("Sales Invoice", "Sales Order", so)
            original = orders[so].get(so_line)
            open_qty = _d(line.quantity) - min(_d(line.quantity), order_billed[so].get(so_line, Decimal("0")))
            order_billed[so][so_line] = order_billed[so].get(so_line, Decimal("0")) + max(open_qty, Decimal("0"))
            remaining = open_qty
        else:
            remaining = _d(line.quantity) - already.get(key, Decimal("0"))
        if remaining <= 0:
            continue
        item = _item(line.item_code)
        account = (getattr(original, "revenue_account", None) if original else None) or (getattr(item, "income_account", None) if item else None)
        if not account:
            throw(f"{line.item_code or 'A line'}: set an Income Account on the item to invoice this delivery.")
        rate = _d(getattr(original, "rate", None) if original else getattr(line, "rate", 0))
        pct = _d(getattr(original, "discount_percentage", None) if original else getattr(line, "discount_percentage", 0))
        disc = _d(getattr(original, "discount_amount", None) if original else getattr(line, "discount_amount", 0))
        amount = _net_amount(rate, pct, disc, remaining)
        tax_rate = _d(getattr(original, "tax_rate", 0)) if original else Decimal("0")
        row = {"item_code": line.item_code, "item_name": getattr(line, "item_name", None), "description": line.description or line.item_code,
               "quantity": remaining, "uom": line.uom, "conversion_factor": line.conversion_factor or 1, "account": account, "rate": rate,
               "discount_percentage": pct, "discount_amount": disc, "amount": amount}
        if original is not None and tax_rate:
            row.update({"tax_account": getattr(original, "tax_account", None), "tax_code": getattr(original, "tax_code", None), "tax_rate": tax_rate,
                        "tax_amount": (amount * tax_rate / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)})
        if from_order:
            row.update({"source_doctype": "Sales Order", "source_document": so, "source_line": so_line})
        else:
            row.update({"source_doctype": "Delivery Note", "source_document": dn.name, "source_line": key})
        lines.append(row)
    return lines


def _invoice_from_delivery_lines(dn, overrides):
    lines = delivery_invoice_lines(dn)
    if not lines:
        throw("Everything on this Delivery Note has already been invoiced.")
    today = date.today().isoformat()
    inv = new_doc("Sales Invoice", invoice_date=overrides.get("invoice_date") or today, posting_date=overrides.get("posting_date") or today,
                  due_date=overrides.get("due_date") or today, party=dn.party, currency=dn.currency, exchange_rate=dn.exchange_rate,
                  source_doctype="Delivery Note", source_document=dn.name, party_reference=overrides.get("party_reference"),
                  narration=overrides.get("narration") or f"Sales Invoice created from Delivery Note {dn.name}", lines=lines)
    inv.insert()
    return inv


def create_sales_invoice_from_waybill(wb_name, overrides=None):
    wb = get_doc("Waybill", wb_name)
    if int(wb.docstatus or 0) != 1:
        throw("Only a submitted Waybill can be invoiced.")
    if not wb.delivery_note:
        throw("This Waybill has no Delivery Note to invoice.")
    overrides = dict(overrides or {})
    overrides.setdefault("narration", f"Sales Invoice created from Waybill {wb.name} (Delivery Note {wb.delivery_note})")
    return create_sales_invoice_from_delivery(wb.delivery_note, overrides)


def create_sales_invoice_from_quotation(q_name, overrides=None):
    """Invoice an approved quotation directly. Stock items are issued by the invoice itself (Update Stock), so a warehouse is needed."""
    from .conversion import _converted_quantities
    overrides = dict(overrides or {}); _check_overrides(overrides, ("warehouse", "revenue_account", "quantities"))
    quantities = overrides.pop("quantities", None) or {}
    with db.transaction():
        q = get_doc("Sales Quotation", q_name); q._lock_and_check()
        if int(q.docstatus or 0) != 1: throw("Only a submitted Sales Quotation can be invoiced.")
        if q.approval_status != "Approved": throw("Only approved Sales Quotations can be invoiced.")
        if str(q.valid_until) < date.today().isoformat(): throw("This Sales Quotation has expired. Create and approve a revised quotation.")
        ordered = _converted_quantities("Sales Quotation", q_name, "Sales Order")
        from velora_erp.finance.fulfilment import line_totals
        invoiced = line_totals("Sales Invoice", "Sales Quotation", q_name)
        lines = []; stock = False
        for src in q.lines or []:
            key = str(src.name); remaining = _d(src.quantity) - ordered.get(key, Decimal("0")) - invoiced.get(key, Decimal("0"))
            if remaining <= 0: continue
            qty = _d(quantities.get(key, remaining))
            if qty <= 0 or qty > remaining: throw(f"Line {key}: quantity must be greater than zero and cannot exceed the {remaining} not yet ordered or invoiced.")
            item = _item(src.item_code)
            account = overrides.get("revenue_account") or (getattr(item, "income_account", None) if item else None)
            if not account: throw(f"Line {key}: select the Revenue Account (or set an Income Account on the item) to invoice a quotation directly.")
            if item and item.is_stock_item: stock = True
            amount = _net_amount(src.rate, src.discount_percentage, src.discount_amount, qty)
            lines.append({"source_line": key, "item_code": src.item_code, "description": src.description or "Quotation line", "quantity": qty, "uom": src.uom,
                          "conversion_factor": src.conversion_factor or 1, "account": account, "rate": src.rate, "discount_percentage": src.discount_percentage or 0,
                          "discount_amount": src.discount_amount or 0, "amount": amount, "cost_rate": src.cost_rate, "cost_source": src.cost_source,
                          "price_basis": src.price_basis, "warehouse": getattr(src, "warehouse", None)})
        if not lines: throw("Everything on this quotation has already been ordered or invoiced.")
        warehouse = overrides.get("warehouse") or next((l["warehouse"] for l in lines if l.get("warehouse")), None)
        if stock and not warehouse: throw("Select the Dispatch Warehouse: the invoice issues the stock items itself (Update Stock).")
        inv = new_doc("Sales Invoice", invoice_date=overrides.get("invoice_date") or date.today().isoformat(), posting_date=overrides.get("posting_date") or date.today().isoformat(),
                      due_date=overrides.get("due_date") or date.today().isoformat(), party=q.party, currency=q.currency, exchange_rate=q.exchange_rate,
                      source_doctype="Sales Quotation", source_document=q.name, party_reference=overrides.get("party_reference"),
                      update_stock=1 if stock else 0, warehouse=warehouse if stock else None,
                      narration=overrides.get("narration") or f"Sales Invoice created from Sales Quotation {q.name}", lines=lines)
        inv.insert()
        return inv


def create_purchase_invoice_from_order(po_name, overrides=None):
    """Invoice a Purchase Order directly (the receipt is optional). Stock items not yet received are received by the invoice (Update Stock)."""
    from .conversion import _converted_quantities
    overrides = dict(overrides or {}); _check_overrides(overrides, ("warehouse", "expense_account", "quantities"))
    quantities = overrides.pop("quantities", None) or {}
    with db.transaction():
        po = get_doc("Purchase Order", po_name); po._lock_and_check()
        if int(po.docstatus or 0) != 1: throw("Only a submitted Purchase Order can be invoiced.")
        if po.document_status == "Closed": throw("This Purchase Order is closed.")
        received = _converted_quantities("Purchase Order", po_name, "Purchase Receipt")
        from velora_erp.finance.fulfilment import line_totals
        invoiced = line_totals("Purchase Invoice", "Purchase Order", po_name)
        lines = []; stock = False
        for src in po.lines or []:
            key = str(src.name); item = _item(src.item_code)
            is_stock = bool(item and item.is_stock_item)
            # goods already on a receipt are invoiced from that receipt; services have no receipt
            remaining = _d(src.quantity) - invoiced.get(key, Decimal("0")) - (received.get(key, Decimal("0")) if is_stock else Decimal("0"))
            if remaining <= 0: continue
            qty = _d(quantities.get(key, remaining))
            if qty <= 0 or qty > remaining: throw(f"Line {key}: quantity must be greater than zero and cannot exceed the {remaining} not yet received or invoiced.")
            account = overrides.get("expense_account") or (getattr(item, "expense_account", None) if item else None)
            if not account: throw(f"Line {key}: select the Expense Account (or set one on the item) to invoice a purchase order directly.")
            if is_stock: stock = True
            amount = _net_amount(src.rate, getattr(src, "discount_percentage", 0), getattr(src, "discount_amount", 0), qty)
            lines.append({"source_line": key, "item_code": src.item_code, "description": src.description or "Purchase order line", "quantity": qty, "uom": src.uom,
                          "conversion_factor": src.conversion_factor or 1, "account": account, "rate": src.rate, "discount_percentage": getattr(src, "discount_percentage", 0) or 0,
                          "discount_amount": getattr(src, "discount_amount", 0) or 0, "amount": amount, "cost_centre": getattr(src, "cost_centre", None),
                          "warehouse": getattr(src, "warehouse", None)})
        if not lines: throw("Everything on this Purchase Order has been received or invoiced. Invoice received goods from their Purchase Receipt.")
        warehouse = overrides.get("warehouse") or next((l["warehouse"] for l in lines if l.get("warehouse")), None)
        if stock and not warehouse: throw("Select the Warehouse: the invoice receives the stock items itself (Update Stock).")
        today = date.today().isoformat()
        inv = new_doc("Purchase Invoice", invoice_date=overrides.get("invoice_date") or today, posting_date=overrides.get("posting_date") or today, due_date=overrides.get("due_date") or today,
                      party=po.party, currency=po.currency, exchange_rate=po.exchange_rate, source_doctype="Purchase Order", source_document=po.name,
                      party_reference=overrides.get("party_reference"), update_stock=1 if stock else 0, warehouse=warehouse if stock else None,
                      narration=overrides.get("narration") or f"Purchase Invoice created from Purchase Order {po.name}", lines=lines)
        inv.insert()
        return inv
