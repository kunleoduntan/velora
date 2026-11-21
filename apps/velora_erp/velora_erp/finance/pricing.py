"""Inventory cost-based selling price and server-enforced cost floor.

Pricing uses Inventory Item as the single stock master. The current Stock Ledger
is authoritative for carrying cost; Inventory Item.standard_rate is only a
configured fallback when no positive stock valuation is available.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import func, select
from velora import db, get_doc, get_list, throw
from velora.db.tables import get_table

ZERO = Decimal("0")
CENT = Decimal("0.01")
BASIS_AUTO = "Automatic"
BASIS_MANUAL = "Manual"
BASIS_KEYS = {"Customer Group": "group", "Item": "item", "Default": "default"}


def dec(value, label="Amount"):
    try:
        result = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        throw(f"{label} must be numeric.")
    if not result.is_finite():
        throw(f"{label} must be finite.")
    return result


def money(value):
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _settings():
    rows = get_list("Inventory Settings", fields=[
        "name", "selling_cost_basis", "enable_cost_based_selling_price", "block_selling_below_cost",
        "require_cost_for_stock_sales", "default_selling_margin_percent",
        "selling_price_basis", "price_rounding_step", "allow_manual_selling_price",
        "strict_selling_price",
    ], limit=1, ignore_permissions=True)
    if not rows:
        settings = {
            "selling_cost_basis": "Last Purchase Cost",
            "enable_cost_based_selling_price": 0,
            "block_selling_below_cost": 1,
            "require_cost_for_stock_sales": 1,
            "default_selling_margin_percent": 0,
            "selling_price_basis": "Markup on Cost",
            "price_rounding_step": 0,
            "allow_manual_selling_price": 1,
            "strict_selling_price": 0,
        }
    else:
        settings = rows[0]
    from velora_erp.configuration import apply_governed_settings
    return apply_governed_settings("Inventory Settings", settings)


def round_price(value, step=0):
    step = dec(step, "Price rounding step")
    value = dec(value, "Selling price")
    if step > 0:
        return money((value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step)
    return money(value)


def raw_price(cost, margin, basis="Markup on Cost"):
    cost, margin = dec(cost, "Cost"), dec(margin, "Margin")
    if cost <= 0 or margin < 0:
        return None
    if basis == "Margin on Selling Price":
        if margin >= 100:
            return None
        return cost / (Decimal("1") - margin / Decimal("100"))
    if basis != "Markup on Cost":
        throw("Selling Price Basis must be Markup on Cost or Margin on Selling Price.")
    return cost * (Decimal("1") + margin / Decimal("100"))


def get_latest_purchase_cost(item_code):
    """Return the latest submitted receipt cost per stock UOM, including landed cost.

    Purchase Invoice lines matched to a Purchase Receipt do not replace receipt cost;
    inventory is physically received through Purchase Receipt in this release.
    """
    if not db.exists("Inventory Item", item_code):
        return None
    receipt_table = get_table("Purchase Receipt")
    line_table = get_table("Purchase Receipt Line")
    with db.transaction() as conn:
        receipt_line = conn.execute(select(
            receipt_table.c.name.label("receipt_name"),
            receipt_table.c.document_date.label("purchase_date"),
            receipt_table.c.exchange_rate.label("exchange_rate"),
            line_table.c.name.label("line_name"),
            line_table.c.quantity.label("quantity"),
            line_table.c.valuation_rate.label("valuation_rate"),
        ).select_from(receipt_table.join(line_table, line_table.c.parent == receipt_table.c.name)).where(
            receipt_table.c.docstatus == 1, line_table.c.item_code == item_code
        ).order_by(receipt_table.c.document_date.desc(), receipt_table.c.creation.desc(), receipt_table.c.name.desc(),
                   line_table.c.creation.desc(), line_table.c.name.desc()).limit(1)).mappings().first()
    if not receipt_line:
        return None
    receipt_doc = get_doc("Purchase Receipt", receipt_line["receipt_name"], ignore_permissions=True)
    receipt_detail = next((line for line in receipt_doc.lines or [] if str(getattr(line, "name", "")) == str(receipt_line["line_name"])), None)
    if not receipt_detail:
        return None
    factor = dec(getattr(receipt_detail, "conversion_factor", 1) or 1, "Receipt conversion factor")
    qty = dec(receipt_line["quantity"], "Received quantity") * factor
    if qty <= 0 or factor <= 0:
        return None
    fx = dec(receipt_line["exchange_rate"] or 1, "Purchase Receipt exchange rate")
    entered_rate = dec(receipt_line["valuation_rate"], "Purchase Receipt valuation rate")
    if entered_rate > 0:
        base_cost = entered_rate * fx / factor
    else:
        item = get_doc("Inventory Item", item_code)
        base_cost = dec(getattr(item, "standard_rate", 0), "Inventory Item Standard Cost Rate")
    if base_cost <= 0:
        return None
    landed_base = ZERO
    vouchers = get_list("Landed Cost Voucher", filters={"purchase_receipt": receipt_line["receipt_name"], "docstatus": 1},
        fields=["name", "exchange_rate"], limit=5000, ignore_permissions=True)
    for voucher_row in vouchers:
        voucher = get_doc("Landed Cost Voucher", voucher_row["name"], ignore_permissions=True)
        voucher_fx = dec(getattr(voucher, "exchange_rate", 1) or 1, "Landed Cost exchange rate")
        for allocation in voucher.allocations or []:
            if str(getattr(allocation, "source_line", "")) == str(receipt_line["line_name"]):
                landed_base += dec(getattr(allocation, "allocated_amount", 0), "Allocated landed cost") * voucher_fx
    unit_cost = base_cost + landed_base / qty
    return unit_cost, receipt_line["purchase_date"], receipt_line["receipt_name"]


def get_inventory_cost(item_code, warehouse=None, batch=None, serial_number=None):
    """Resolve selling cost using the configured cost basis and authoritative ledgers.

    Default is Last Purchase Cost, including allocated landed costs. Current carrying
    valuation and Inventory Item Standard Cost Rate are controlled fallbacks.
    """
    item = get_doc("Inventory Item", item_code)
    if item.disabled or not item.is_stock_item:
        return None, None
    settings = _settings()
    if (settings.get("selling_cost_basis") or "Last Purchase Cost") == "Last Purchase Cost":
        stored = dec(getattr(item, "last_purchase_cost", 0), "Last Purchase Cost")
        reference = getattr(item, "last_purchase_reference", None)
        if stored > 0:
            return stored, f"Last Purchase Cost ({reference})" if reference else "Last Purchase Cost"
        latest = get_latest_purchase_cost(item_code)
        if latest and latest[0] > 0:
            return latest[0], f"Last Purchase Cost ({latest[2]})"
    table = get_table("Stock Ledger Record")
    conditions = [table.c.item_code == item_code]
    if warehouse:
        conditions.append(table.c.warehouse == warehouse)
    if batch:
        conditions.append(table.c.batch == batch)
    if serial_number:
        conditions.append(table.c.serial_number == serial_number)
    with db.transaction() as conn:
        result = conn.execute(select(
            func.coalesce(func.sum(table.c.actual_qty), 0).label("qty"),
            func.coalesce(func.sum(table.c.stock_value_difference), 0).label("value"),
        ).where(*conditions)).mappings().one()
    qty, value = dec(result["qty"], "Inventory quantity"), dec(result["value"], "Inventory value")
    if qty > 0 and value > 0:
        return value / qty, "Current Stock Ledger valuation"
    fallback = dec(getattr(item, "standard_rate", 0), "Inventory Item Standard Cost Rate")
    if fallback > 0:
        return fallback, "Inventory Item Standard Cost Rate"
    return None, None


def refresh_last_purchase_cost(item_code):
    """Refresh Inventory Item's read-only last-purchase-cost snapshot after receipt/capitalisation."""
    if not db.exists("Inventory Item", item_code):
        return False
    latest = get_latest_purchase_cost(item_code)
    if not latest:
        return False
    cost, purchase_date, reference = latest
    item = get_doc("Inventory Item", item_code)
    if (dec(getattr(item, "last_purchase_cost", 0), "Last Purchase Cost") == money(cost)
            and str(getattr(item, "last_purchase_date", "") or "") == str(purchase_date or "")
            and getattr(item, "last_purchase_reference", None) == reference):
        return False
    item.flags.cost_refresh = True
    item.last_purchase_cost = money(cost)
    item.last_purchase_date = purchase_date
    item.last_purchase_reference = reference
    item.cost_source = f"Purchase Receipt {reference}; landed cost included where allocated"
    item.save(ignore_permissions=True)
    return True


def refresh_all_last_purchase_costs():
    """One-time migration refresh for existing inventory items with historic receipts."""
    rows = get_list("Inventory Item", fields=["name"], limit=100000, ignore_permissions=True)
    refreshed = 0
    for row in rows:
        if refresh_last_purchase_cost(row["name"]):
            refreshed += 1
    return refreshed


def _customer_group(customer):
    if not customer:
        return None
    party = get_doc("Customer", customer)
    return getattr(party, "customer_group", None)


def _group_margin(group_name):
    seen = set()
    while group_name and group_name not in seen:
        seen.add(group_name)
        group = get_doc("Customer Group", group_name)
        margin = dec(getattr(group, "selling_margin_percent", 0), "Customer Group selling margin")
        if margin > 0:
            return margin, group_name
        group_name = getattr(group, "parent_group", None)
    return None, None


def resolve_price(item_code, customer_group=None, basis=None, warehouse=None, batch=None, serial_number=None, settings=None):
    """Resolve Automatic/Customer Group/Item/Default/Manual pricing for an inventory item."""
    s = settings or _settings()
    item = get_doc("Inventory Item", item_code)
    if item.disabled:
        throw(f"Inventory Item {item_code} is disabled.")
    if not item.is_stock_item:
        return None
    cost, cost_source = get_inventory_cost(item_code, warehouse, batch, serial_number)
    out = {"item_code": item_code, "cost": cost, "cost_source": cost_source, "priced": False, "candidates": []}
    if item.pricing_mode == "Fixed Price":
        fixed = dec(getattr(item, "standard_selling_rate", 0), "Fixed Selling Rate")
        if fixed <= 0:
            out["reason"] = "Pricing Mode is Fixed Price but no Standard Selling Rate is configured."
            return out
        out.update(priced=True, price=money(fixed), raw=fixed, source="Fixed Item Price", basis_key="item")
        out["candidates"].append({"key": "item", "raw": fixed, "price": money(fixed), "source": "Fixed Item Price", "margin": None})
        return out
    if cost is None or cost <= 0:
        out["reason"] = "No inventory cost is available. Post opening stock or configure a positive Inventory Item Standard Rate."
        return out
    group_margin, group_source = _group_margin(customer_group) if customer_group else (None, None)
    specs = [
        ("group", group_margin, f"Customer Group {group_source}" if group_source else None),
        ("item", dec(getattr(item, "selling_margin_percent", 0), "Item selling margin") or None, "Item margin"),
        ("default", dec(s.get("default_selling_margin_percent", 0), "Default selling margin") or None, "Default margin"),
    ]
    for key, margin, source in specs:
        raw = raw_price(cost, margin, s.get("selling_price_basis") or "Markup on Cost") if margin and margin > 0 else None
        if raw is not None:
            out["candidates"].append({"key": key, "raw": raw, "price": round_price(raw, s.get("price_rounding_step", 0)), "source": source, "margin": margin})
    if not out["candidates"]:
        out["reason"] = "No selling margin is configured on the Customer Group, Inventory Item or Inventory Settings."
        return out
    wanted = BASIS_KEYS.get(basis)
    by_key = {row["key"]: row for row in out["candidates"]}
    chosen = by_key.get(wanted) or next(by_key[key] for key in ("group", "item", "default") if key in by_key)
    out.update(priced=True, price=chosen["price"], raw=chosen["raw"], source=chosen["source"], basis_key=chosen["key"],
               fell_back=bool(wanted and wanted not in by_key), wanted=basis if wanted and wanted not in by_key else None)
    return out


def price_row(*, doctype, item_code, customer=None, customer_group=None, currency="NGN", exchange_rate=1,
              uom=None, conversion_factor=1, quantity=1, discount_percentage=0, discount_amount=0,
              price_basis="Automatic", warehouse=None, batch=None, serial_number=None, settings=None):
    s = settings or _settings()
    if price_basis == BASIS_MANUAL:
        if not s.get("allow_manual_selling_price", 1):
            throw("Manual selling prices are disabled in Inventory Settings.")
        return {"manual": True, "priced": False, "name": None}
    if not customer_group and customer:
        customer_group = _customer_group(customer)
    info = resolve_price(item_code, customer_group, price_basis, warehouse, batch, serial_number, s)
    if info is None:
        return None
    if not info.get("priced"):
        return {"priced": False, "unpriced": True, "reason": info.get("reason"), "cost": info.get("cost"), "cost_source": info.get("cost_source")}
    factor = dec(conversion_factor or 1, "Conversion Factor")
    fx = dec(exchange_rate or 1, "Exchange Rate")
    qty = dec(quantity or 0, "Quantity")
    if factor <= 0 or fx <= 0:
        throw("Conversion Factor and Exchange Rate must be greater than zero.")
    # Margin prices are defined per stock unit in company currency. Convert once to
    # the selected sales UOM and transaction currency.
    raw_uom = info["raw"] * factor / fx
    price = round_price(raw_uom, s.get("price_rounding_step", 0))
    if dec(discount_percentage or 0) < 0 or dec(discount_percentage or 0) >= 100:
        throw("Discount Percentage must be at least zero and less than 100.")
    if dec(discount_amount or 0) < 0:
        throw("Discount Amount cannot be negative.")
    net_rate = price * (Decimal("1") - dec(discount_percentage or 0) / Decimal("100")) - dec(discount_amount or 0)
    amount = money(net_rate * qty)
    cost_uom = dec(info["cost"]) * factor
    candidates = {row["key"]: round_price(row["raw"] * factor / fx, s.get("price_rounding_step", 0)) for row in info["candidates"]}
    return {
        "priced": True, "price": price, "rate": money(net_rate), "amount": amount,
        "cost_rate": money(cost_uom / fx), "cost_base_rate": cost_uom,
        "cost_source": info["cost_source"],
        "price_note": (f"{info.get('wanted')} price not available: {info['source']}" if info.get("fell_back") else info["source"]),
        "group_price": candidates.get("group"), "item_price": candidates.get("item"),
        "default_price": candidates.get("default"), "price_basis": info["basis_key"],
        "fell_back": info.get("fell_back", False), "reason": info.get("reason"),
    }


def _row_effective_amount(line, doctype):
    qty = dec(getattr(line, "quantity", 0), "Sales quantity")
    if qty <= 0:
        throw("Sales quantity must be greater than zero for cost-floor validation.")
    if doctype == "Sales Invoice":
        amount = dec(getattr(line, "amount", 0), "Sales line net amount")
        return amount / qty
    rate = dec(getattr(line, "rate", 0), "Sales rate")
    discount_pct = dec(getattr(line, "discount_percentage", 0), "Discount Percentage")
    discount_amt = dec(getattr(line, "discount_amount", 0), "Discount Amount")
    if discount_pct < 0 or discount_pct >= 100 or discount_amt < 0:
        throw("Sales discounts must be non-negative and percentage discounts must be below 100%.")
    return rate * (Decimal("1") - discount_pct / Decimal("100")) - discount_amt


def _line_factor(line, item):
    factor = dec(getattr(line, "conversion_factor", 1) or 1, "Conversion Factor")
    if factor <= 0:
        throw(f"{item.name}: Conversion Factor must be greater than zero.")
    return factor


def apply_sales_pricing(doc, doctype):
    """Apply configured margin pricing before document totals are validated."""
    s = _settings()
    if not s.get("enable_cost_based_selling_price"):
        if not s.get("allow_manual_selling_price", 1):
            for index, line in enumerate(getattr(doc, "lines", []) or [], 1):
                if getattr(line, "price_basis", None) == BASIS_MANUAL:
                    throw(f"Line {index}: Manual selling price is disabled in Inventory Settings.")
        return
    customer = getattr(doc, "party", None)
    customer_group = _customer_group(customer) if customer else None
    fx = dec(getattr(doc, "exchange_rate", 1) or 1, "Exchange Rate")
    if fx <= 0:
        throw("Exchange Rate must be greater than zero.")
    problems = []
    for index, line in enumerate(getattr(doc, "lines", []) or [], 1):
        item_code = getattr(line, "item_code", None)
        if not item_code:
            continue
        # Prices copied from an approved quotation are contractual; do not silently reprice them.
        if (getattr(line, "source_doctype", None) or getattr(doc, "source_doctype", None)) in ("Sales Quotation", "Sales Order") and getattr(line, "source_line", None):
            continue
        try:
            item = get_doc("Inventory Item", item_code)
        except Exception:
            continue  # non-inventory/service lines retain their entered rate
        if item.disabled or not item.is_stock_item:
            continue
        basis = getattr(line, "price_basis", None) or BASIS_AUTO
        if basis not in (BASIS_AUTO, BASIS_MANUAL, *BASIS_KEYS):
            throw(f"Line {index}: invalid Price Basis {basis}.")
        if basis == BASIS_MANUAL:
            if not s.get("allow_manual_selling_price", 1):
                throw(f"Line {index}: Manual selling price is disabled in Inventory Settings.")
            line.price_note = "Manual price"
            continue
        priced = price_row(
            doctype=doctype, item_code=item_code, customer=customer, customer_group=customer_group,
            currency=getattr(doc, "currency", "NGN"), exchange_rate=fx,
            uom=getattr(line, "uom", None), conversion_factor=_line_factor(line, item),
            quantity=getattr(line, "quantity", 0), discount_percentage=getattr(line, "discount_percentage", 0),
            discount_amount=getattr(line, "discount_amount", 0), price_basis=basis,
            warehouse=getattr(line, "warehouse", None), batch=getattr(line, "batch", None),
            serial_number=getattr(line, "serial_number", None), settings=s,
        )
        if priced is None:
            continue
        if not priced.get("priced"):
            if s.get("strict_selling_price"):
                problems.append(f"Line {index}: {item_code} has no configured selling price. {priced.get('reason')}")
            continue
        line.rate = priced["price"]
        line.amount = priced["amount"]
        line.cost_rate = priced["cost_rate"]
        line.cost_source = priced["cost_source"]
        line.price_note = priced["price_note"]
        line.price_basis = basis if basis != BASIS_AUTO else BASIS_AUTO
        line.group_price = priced.get("group_price")
        line.item_price = priced.get("item_price")
        line.default_price = priced.get("default_price")
        if getattr(line, "tax_rate", None) is not None and getattr(line, "tax_account", None):
            line.tax_amount = money(dec(line.amount) * dec(line.tax_rate) / Decimal("100"))
    if problems:
        throw("<br>".join(problems))


def enforce_cost_floor(doc, doctype):
    """Reject sales below current inventory cost, after discounts and FX conversion."""
    s = _settings()
    if not s.get("block_selling_below_cost"):
        return
    fx = dec(getattr(doc, "exchange_rate", 1) or 1, "Exchange Rate")
    if fx <= 0:
        throw("Exchange Rate must be greater than zero.")
    problems = []
    for index, line in enumerate(getattr(doc, "lines", []) or [], 1):
        item_code = getattr(line, "item_code", None)
        if not item_code:
            continue
        try:
            item = get_doc("Inventory Item", item_code)
        except Exception:
            continue
        if item.disabled or not item.is_stock_item:
            continue
        qty = dec(getattr(line, "quantity", 0), f"Line {index} Quantity")
        if qty <= 0:
            continue
        cost, source = get_inventory_cost(item_code, getattr(line, "warehouse", None),
            getattr(line, "batch", None), getattr(line, "serial_number", None))
        if cost is None or cost <= 0:
            if s.get("require_cost_for_stock_sales", 1):
                problems.append(f"Line {index}: {item_code} has no positive inventory cost. Configure an opening stock valuation or Inventory Item Standard Rate before selling it.")
            continue
        factor = _line_factor(line, item)
        effective_rate = _row_effective_amount(line, doctype) * fx
        cost_rate = cost * factor
        if effective_rate + Decimal("0.005") < cost_rate:
            problems.append(
                f"Line {index}: {item_code} selling rate after discounts is {money(effective_rate)} in base currency per {getattr(line, 'uom', None) or item.stock_uom}; current cost is {money(cost_rate)} ({source}). Selling below cost is blocked."
            )
        line.cost_rate = money(cost_rate / fx)
        line.cost_source = source
    if problems:
        throw("Selling Below Cost: " + "<br>".join(problems))


def explain_item_price(item_code, *, customer=None, customer_group=None, uom=None,
                       conversion_factor=1, currency="NGN", exchange_rate=1,
                       price_basis="Automatic", warehouse=None, batch=None, serial_number=None):
    """Return an auditable explanation of the price and cost floor for one stock item."""
    if not item_code or not db.exists("Inventory Item", item_code):
        throw("Select a valid Inventory Item to explain its selling price.")
    settings = _settings()
    item = get_doc("Inventory Item", item_code)
    if item.disabled:
        throw(f"Inventory Item {item_code} is disabled.")
    if not item.is_stock_item:
        return {
            "item_code": item_code, "applicable": False,
            "message": "This is a non-stock item; inventory cost-based pricing does not apply.",
        }
    factor = dec(conversion_factor or 1, "Conversion Factor")
    fx = dec(exchange_rate or 1, "Exchange Rate")
    if factor <= 0 or fx <= 0:
        throw("Conversion Factor and Exchange Rate must be greater than zero.")
    group = customer_group or (_customer_group(customer) if customer else None)
    cost, cost_source = get_inventory_cost(item_code, warehouse, batch, serial_number)
    info = resolve_price(item_code, group, price_basis, warehouse, batch, serial_number, settings)
    stock_uom = getattr(item, "stock_uom", None)
    selected_uom = uom or stock_uom
    cost_stock = dec(cost, "Inventory Cost") if cost is not None else None
    cost_uom = cost_stock * factor if cost_stock is not None else None
    candidates = []
    if info:
        for candidate in info.get("candidates", []):
            candidates.append({
                "basis": candidate["key"],
                "source": candidate["source"],
                "margin_percent": candidate.get("margin"),
                "price": round_price(candidate["raw"] * factor / fx, settings.get("price_rounding_step", 0)),
            })
    return {
        "item_code": item_code,
        "item_name": getattr(item, "item_name", item_code),
        "applicable": True,
        "pricing_enabled": bool(settings.get("enable_cost_based_selling_price")),
        "below_cost_block_enabled": bool(settings.get("block_selling_below_cost")),
        "require_cost_enabled": bool(settings.get("require_cost_for_stock_sales")),
        "pricing_mode": getattr(item, "pricing_mode", "Margin Based"),
        "requested_basis": price_basis or BASIS_AUTO,
        "applied_basis": info.get("basis_key") if info else None,
        "price_source": info.get("source") if info else None,
        "price_available": bool(info and info.get("priced")),
        "price_reason": info.get("reason") if info else None,
        "currency": currency,
        "exchange_rate": fx,
        "uom": selected_uom,
        "stock_uom": stock_uom,
        "conversion_factor": factor,
        "cost_per_stock_unit_base": money(cost_stock) if cost_stock is not None else None,
        "cost_per_uom_base": money(cost_uom) if cost_uom is not None else None,
        "cost_per_uom_transaction": money(cost_uom / fx) if cost_uom is not None else None,
        "cost_source": cost_source,
        "candidates": candidates,
        "chosen_price": next((row["price"] for row in candidates if row["basis"] == (info or {}).get("basis_key")), None),
    }


def get_row_prices(doctype, args):
    """Server endpoint used by native Desk client scripts for live pricing and price explanation."""
    if doctype not in {"Sales Invoice", "Sales Order"}:
        throw("Live inventory pricing is available only on Sales Invoice and Sales Order.")
    from velora.permissions import check_permission
    from velora.meta.registry import registry
    check_permission(registry.get(doctype), "read")
    if args.get("explain") or args.get("explain_rows") is not None:
        requests = args.get("explain_rows")
        if requests is None:
            requests = [args.get("explain")]
        if not isinstance(requests, list) or not requests or len(requests) > 100:
            throw("Price explanation must contain between 1 and 100 inventory rows.")
        explanations = []
        for request in requests:
            if not isinstance(request, dict):
                throw("Each price explanation row must be an object.")
            explanations.append(explain_item_price(
                request.get("item_code"), customer=request.get("customer") or args.get("customer"),
                customer_group=request.get("customer_group") or args.get("customer_group"),
                uom=request.get("uom"), conversion_factor=request.get("conversion_factor", 1),
                currency=request.get("currency") or args.get("currency") or "NGN",
                exchange_rate=request.get("exchange_rate") or args.get("exchange_rate") or 1,
                price_basis=request.get("price_basis") or "Automatic",
                warehouse=request.get("warehouse"), batch=request.get("batch"),
                serial_number=request.get("serial_number"),
            ))
        return explanations if args.get("explain_rows") is not None else explanations[0]
    settings = _settings()
    if not settings.get("enable_cost_based_selling_price"):
        return []
    source_rows = args.get("rows") or []
    if not isinstance(source_rows, list) or len(source_rows) > 200:
        throw("A live pricing request may contain at most 200 sales rows.")
    customer = args.get("customer")
    group = args.get("customer_group") or (_customer_group(customer) if customer else None)
    fx = args.get("exchange_rate") or 1
    result = []
    for index, source in enumerate(source_rows):
        item_code = source.get("item_code")
        if not item_code:
            continue
        try:
            item = get_doc("Inventory Item", item_code)
        except Exception:
            continue
        if item.disabled or not item.is_stock_item:
            continue
        basis = source.get("price_basis") or BASIS_AUTO
        priced = price_row(
            doctype=doctype, item_code=item_code, customer=customer, customer_group=group,
            currency=args.get("currency") or "NGN", exchange_rate=fx,
            uom=source.get("uom"), conversion_factor=source.get("conversion_factor") or 1,
            quantity=source.get("quantity") or 1, discount_percentage=source.get("discount_percentage") or 0,
            discount_amount=source.get("discount_amount") or 0, price_basis=basis,
            warehouse=source.get("warehouse"), batch=source.get("batch"), serial_number=source.get("serial_number"),
            settings=settings,
        )
        if priced is None:
            continue
        entry = {"index": source.get("index", index), **priced}
        if priced.get("manual"):
            entry["manual"] = True
        elif priced.get("unpriced") and settings.get("strict_selling_price"):
            throw(f"{item_code}: {priced.get('reason')}")
        result.append(entry)
    return result


def enforce_delivery_issue_cost_floor(doc):
    """At dispatch, compare the agreed order price with the actual warehouse issue cost.

    This second check matters for FIFO: the actual oldest cost layer can differ from the
    blended cost used when a Sales Order was priced.
    """
    settings = _settings()
    if not settings.get("block_selling_below_cost"):
        return
    from velora_erp.finance.inventory.ledger import get_issue_valuation
    problems = []
    fx = dec(getattr(doc, "exchange_rate", 1) or 1, "Delivery Note exchange rate")
    orders = {}                                                        # each line may come from a different order, or from none

    def agreed_line(line):
        name = getattr(line, "source_document", None) or getattr(doc, "source_document", None)
        key = str(getattr(line, "source_line", "") or "")
        if not key or not name:
            return line                                                # a line typed in by hand is checked against its own price
        if name not in orders:
            orders[name] = {str(getattr(l, "name", "")): l for l in get_doc("Sales Order", name).lines or []}
        return orders[name].get(key)
    for index, line in enumerate(doc.lines or [], 1):
        item_code = getattr(line, "item_code", None)
        if not item_code or not db.exists("Inventory Item", item_code):
            continue
        item = get_doc("Inventory Item", item_code)
        if item.disabled or not item.is_stock_item:
            continue
        source_line = agreed_line(line)
        if not source_line:
            problems.append(f"Line {index}: the source Sales Order line is missing; the agreed selling price cannot be verified.")
            continue
        factor = dec(getattr(line, "conversion_factor", 1) or 1, "Stock UOM Conversion Factor")
        if factor <= 0:
            throw(f"Line {index}: Stock UOM Conversion Factor must be greater than zero.")
        stock_qty = dec(getattr(line, "quantity", 0), "Delivered quantity") * factor
        issue = get_issue_valuation(item, item.name, doc.warehouse, stock_qty,
            getattr(line, "batch", None), getattr(line, "serial_number", None))
        cost_per_stock_unit = dec(issue["rate"], "Actual issue cost")
        cost_per_sales_uom = cost_per_stock_unit * factor
        line.cost_rate = money(cost_per_sales_uom / fx)
        line.cost_source = "Actual warehouse issue valuation"
        rate = dec(getattr(source_line, "rate", 0), "Agreed selling rate")
        discount_pct = dec(getattr(source_line, "discount_percentage", 0), "Discount Percentage")
        discount_amount = dec(getattr(source_line, "discount_amount", 0), "Discount Amount")
        if discount_pct < 0 or discount_pct >= 100 or discount_amount < 0:
            throw(f"Line {index}: source Sales Order discounts are invalid.")
        net_rate = rate * (Decimal("1") - discount_pct / Decimal("100")) - discount_amount
        selling_base = net_rate * fx
        if selling_base + Decimal("0.005") < cost_per_sales_uom:
            problems.append(
                f"Line {index}: agreed selling rate after discounts is {money(selling_base)} in base currency per {getattr(line, 'uom', None) or item.stock_uom}; actual warehouse issue cost is {money(cost_per_sales_uom)}. Dispatch below cost is blocked."
            )
    if problems:
        throw("Selling Below Cost at Dispatch: " + "<br>".join(problems))
