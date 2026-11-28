"""Quantity-safe conversion of submitted Sales Orders into draft Sales Invoices."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
from velora import db, get_doc, get_list, new_doc, throw


def _d(value, label):
    try: result = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError): throw(f"{label} must be numeric.")
    if not result.is_finite(): throw(f"{label} must be finite.")
    return result


def delivered_quantity_for_order_line(order_name, source_line, source_factor=1):
    """Submitted delivery quantity of one Sales Order line (a delivery's factor must equal its order line's, so no conversion is needed)."""
    from velora_erp.finance.fulfilment import line_totals
    return line_totals("Delivery Note", "Sales Order", order_name, statuses=(1,)).get(str(source_line), Decimal("0"))


def _is_stock_item(item_code):
    if not item_code or not db.exists("Inventory Item", item_code): return False
    item = get_doc("Inventory Item", item_code, ignore_permissions=True)
    return bool(getattr(item, "is_stock_item", 0) and not getattr(item, "disabled", 0))


def _prior_invoiced(source_name, exclude=None):
    from velora_erp.finance.fulfilment import line_totals
    return line_totals("Sales Invoice", "Sales Order", source_name, exclude=exclude)


def create_sales_invoice_from_order(order_name, quantities=None, overrides=None, only=None):
    """Create a draft invoice for remaining order quantities; source order is row-locked."""
    overrides = overrides or {}; quantities = quantities or {}
    allowed = {"invoice_date", "posting_date", "due_date", "party_reference", "narration"}
    invalid = set(overrides) - allowed
    if invalid: throw("Unsupported invoice conversion override(s): " + ", ".join(sorted(invalid)))
    with db.transaction():
        order = get_doc("Sales Order", order_name)
        order._lock_and_check()
        if int(order.docstatus or 0) != 1: throw("Only a submitted Sales Order can be invoiced.")
        prior = _prior_invoiced(order_name)
        lines = []
        source_lines = {str(getattr(x, "name", "")): x for x in order.lines or []}
        unknown = set(quantities) - set(source_lines)
        if unknown: throw("Unknown Sales Order line(s): " + ", ".join(sorted(unknown)))
        for key, source in source_lines.items():
            ordered = _d(source.quantity, "Ordered quantity")
            if ordered <= 0: throw(f"Sales Order line {key} has an invalid quantity.")
            already_invoiced = prior.get(key, Decimal("0"))
            remaining = ordered - already_invoiced
            if remaining <= 0: continue
            invoiceable = remaining
            if _is_stock_item(getattr(source, "item_code", None)):
                delivered = delivered_quantity_for_order_line(order.name, key, getattr(source, "conversion_factor", 1) or 1)
                invoiceable = min(remaining, delivered - already_invoiced)
            if invoiceable <= 0: continue
            if only is not None:
                # invoicing one delivery: bill that delivery's quantity, capped by what is still billable
                if key not in only: continue
                invoiceable = min(invoiceable, only[key])
                if invoiceable <= 0: continue
            qty = _d(quantities.get(key, invoiceable), "Invoice quantity")
            if qty <= 0 or qty > invoiceable: throw(f"Line {key}: invoice quantity must be greater than zero and cannot exceed the billable quantity {invoiceable} (ordered quantity less prior invoices, capped by submitted deliveries for stock items).")
            revenue = getattr(source, "revenue_account", None)
            if not revenue: throw(f"Line {key}: configure a Revenue Account on the Sales Order line before invoicing.")
            rate = _d(getattr(source, "rate", 0), "Selling rate")
            pct = _d(getattr(source, "discount_percentage", 0), "Discount percentage")
            disc = _d(getattr(source, "discount_amount", 0), "Discount amount")
            net_rate = rate * (Decimal("1") - pct / Decimal("100")) - disc
            amount = (net_rate * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            tax_rate = _d(getattr(source, "tax_rate", 0), "Tax rate")
            tax_amount = (amount * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            lines.append({
                "source_line": key, "item_code": getattr(source, "item_code", None),
                "quantity": qty, "uom": getattr(source, "uom", None),
                "conversion_factor": getattr(source, "conversion_factor", 1) or 1,
                "account": revenue, "description": getattr(source, "description", "") or "Sales Order line",
                "rate": rate, "discount_percentage": pct, "discount_amount": disc,
                "amount": amount, "tax_account": getattr(source, "tax_account", None),
                "tax_code": getattr(source, "tax_code", None), "tax_rate": tax_rate,
                "tax_amount": tax_amount, "cost_rate": getattr(source, "cost_rate", 0),
                "cost_source": getattr(source, "cost_source", None),
                "cost_centre": getattr(source, "cost_centre", None),
            })
        if not lines: throw("No billable Sales Order quantities remain. Stock items must first be covered by submitted Delivery Notes; other quantities may already be fully invoiced.")
        payload = {
            "invoice_date": overrides.get("invoice_date") or date.today().isoformat(),
            "posting_date": overrides.get("posting_date") or date.today().isoformat(),
            "due_date": overrides.get("due_date") or date.today().isoformat(),
            "party": order.party, "currency": order.currency, "exchange_rate": order.exchange_rate,
            "source_doctype": "Sales Order", "source_document": order.name,
            "party_reference": overrides.get("party_reference"),
            "narration": overrides.get("narration") or f"Sales Invoice created from Sales Order {order.name}",
            "lines": lines,
        }
        invoice = new_doc("Sales Invoice", **payload)
        invoice.insert()
        return invoice
