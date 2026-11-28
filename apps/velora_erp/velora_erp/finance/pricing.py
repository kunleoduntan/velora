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
from velora_erp.finance.multicurrency import base_currency

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
        "strict_selling_price", "purchases_to_average", "minimum_profit_percent",
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
            "purchases_to_average": 3,
            "minimum_profit_percent": 0,
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


BASIS_LAST, BASIS_AVERAGE, BASIS_WEIGHTED, BASIS_FIFO, BASIS_HIGHEST, BASIS_CURRENT = (
    "Last Purchase Cost", "Simple Average of Last Purchases", "Weighted Average of Last Purchases", "FIFO (Oldest Stock on Hand)",
    "Highest of These (Safest)", "Current Inventory Valuation")
COST_BASES = (BASIS_LAST, BASIS_AVERAGE, BASIS_WEIGHTED, BASIS_FIFO, BASIS_HIGHEST, BASIS_CURRENT)
LEGACY_BASES = {"Average of Last Purchases": BASIS_WEIGHTED}       # 2.95.3 called the quantity-weighted one just "Average"
FOLLOW = "Follow Settings"


def recent_purchase_costs(item_code, limit=1):
    """The latest submitted receipt costs per stock UOM (newest first), including landed cost.

    Purchase Invoice lines matched to a Purchase Receipt do not replace receipt cost;
    inventory is physically received through Purchase Receipt in this release.
    Each entry: {"cost", "date", "reference", "quantity"} (quantity in stock UOM).
    """
    if not db.exists("Inventory Item", item_code):
        return []
    receipt_table = get_table("Purchase Receipt")
    line_table = get_table("Purchase Receipt Line")
    with db.transaction() as conn:
        found = conn.execute(select(
            receipt_table.c.name.label("receipt_name"),
            receipt_table.c.document_date.label("purchase_date"),
            receipt_table.c.exchange_rate.label("exchange_rate"),
            line_table.c.name.label("line_name"),
            line_table.c.quantity.label("quantity"),
            line_table.c.valuation_rate.label("valuation_rate"),
        ).select_from(receipt_table.join(line_table, line_table.c.parent == receipt_table.c.name)).where(
            receipt_table.c.docstatus == 1, line_table.c.item_code == item_code
        ).order_by(receipt_table.c.document_date.desc(), receipt_table.c.creation.desc(), receipt_table.c.name.desc(),
                   line_table.c.creation.desc(), line_table.c.name.desc()).limit(max(int(limit), 1) + 20)).mappings().all()   # a few spare for lines that cannot be costed
    out = []
    for receipt_line in found:
        if len(out) >= limit:
            break
        entry = _receipt_line_cost(item_code, receipt_line)
        if entry:
            out.append(entry)
    return out


def _receipt_line_cost(item_code, receipt_line):
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
    return {"cost": base_cost + landed_base / qty, "date": receipt_line["purchase_date"], "reference": receipt_line["receipt_name"], "quantity": qty}


def get_latest_purchase_cost(item_code):
    """(unit cost, date, receipt) of the latest costed receipt, or None."""
    rows = recent_purchase_costs(item_code, 1)
    return (rows[0]["cost"], rows[0]["date"], rows[0]["reference"]) if rows else None


def average_purchase_cost(item_code, count=3, weighted=True):
    """Average cost of the last `count` receipts. Weighted: by quantity, i.e. what the stock really cost.
    Simple: the plain mean of the receipt prices, whatever the quantities."""
    rows = recent_purchase_costs(item_code, count)
    qty = sum((r["quantity"] for r in rows), ZERO)
    if not rows or qty <= 0:
        return None
    if weighted:
        return sum((r["cost"] * r["quantity"] for r in rows), ZERO) / qty, len(rows), rows[0]["reference"]
    return sum((r["cost"] for r in rows), ZERO) / len(rows), len(rows), rows[0]["reference"]


def fifo_cost(item_code, warehouse=None, batch=None, serial_number=None):
    """Unit cost of the oldest stock still on hand (the next to be sold under FIFO). Without a warehouse, the oldest layer anywhere."""
    from velora_erp.finance.inventory.ledger import _fifo_layers_from_ledger
    table = get_table("Stock Ledger Record")
    if warehouse:
        warehouses = [warehouse]
    else:
        with db.transaction() as conn:
            warehouses = [r[0] for r in conn.execute(select(table.c.warehouse).where(table.c.item_code == item_code).distinct()).all()]
    oldest = None
    for wh in warehouses:
        layers = [layer for layer in _fifo_layers_from_ledger(item_code, wh, batch, serial_number) if dec(layer["qty"]) > 0]
        if layers:
            layer = layers[0]
            key = (str(layer.get("date") or ""), str(layer.get("layer_id") or ""))
            if oldest is None or key < oldest[0]:
                oldest = (key, dec(layer["value"]) / dec(layer["qty"]), layer.get("source"))
    return (oldest[1], oldest[2]) if oldest and oldest[1] > 0 else None


def _current_valuation(item_code, warehouse=None, batch=None, serial_number=None):
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
    return value / qty if qty > 0 and value > 0 else None


def cost_basis_for(item, settings=None):
    """The cost basis that applies: the item's own choice, else its Item Group (or a parent group), else Inventory Settings."""
    s = settings or _settings()
    own = LEGACY_BASES.get(getattr(item, "selling_cost_basis", None), getattr(item, "selling_cost_basis", None))
    if own in COST_BASES:
        return own, "Item"
    group, seen = getattr(item, "item_group", None), set()
    while group and group not in seen:
        seen.add(group)
        try:
            doc = get_doc("Item Group", group)
        except Exception:  # noqa: BLE001
            break
        chosen = LEGACY_BASES.get(getattr(doc, "selling_cost_basis", None), getattr(doc, "selling_cost_basis", None))
        if chosen in COST_BASES:
            return chosen, f"Item Group {group}"
        group = getattr(doc, "parent_item_group", None)
    company = LEGACY_BASES.get(s.get("selling_cost_basis"), s.get("selling_cost_basis"))
    return (company if company in COST_BASES else BASIS_LAST), "Inventory Settings"


def cost_methods(item_code, warehouse=None, batch=None, serial_number=None, settings=None):
    """Every cost the item can be priced from, so the person (and the 'highest' rule) can see them side by side:
    {basis: (unit cost, note)}. A method with nothing to go on is left out."""
    s = settings or _settings()
    item = get_doc("Inventory Item", item_code)
    out = {}
    stored = dec(getattr(item, "last_purchase_cost", 0), "Last Purchase Cost")
    ref = getattr(item, "last_purchase_reference", None)
    if stored > 0:
        out[BASIS_LAST] = (stored, f"Last Purchase Cost ({ref})" if ref else "Last Purchase Cost")
    else:
        latest = get_latest_purchase_cost(item_code)
        if latest:
            out[BASIS_LAST] = (latest[0], f"Last Purchase Cost ({latest[2]})")
    count = int(s.get("purchases_to_average") or 3)
    for key, weighted, label in ((BASIS_AVERAGE, False, "Simple average"), (BASIS_WEIGHTED, True, "Quantity-weighted average")):
        avg = average_purchase_cost(item_code, count, weighted)
        if avg:
            out[key] = (avg[0], f"{label} of last {avg[1]} purchase(s)")
    fifo = fifo_cost(item_code, warehouse, batch, serial_number)
    if fifo:
        out[BASIS_FIFO] = (fifo[0], f"FIFO: oldest stock on hand ({fifo[1]})" if fifo[1] else "FIFO: oldest stock on hand")
    current = _current_valuation(item_code, warehouse, batch, serial_number)
    if current:
        out[BASIS_CURRENT] = (current, "Current Stock Ledger valuation")
    return out


def get_inventory_cost(item_code, warehouse=None, batch=None, serial_number=None):
    """Resolve the cost that selling price and the profit floor are built on, using the policy:
    Item, then Item Group, then Inventory Settings. If the chosen method has nothing to go on yet
    (no purchase, no stock) the next safest available cost is used and the source says so.
    """
    item = get_doc("Inventory Item", item_code)
    if item.disabled or not item.is_stock_item:
        return None, None
    settings = _settings()
    basis, where = cost_basis_for(item, settings)
    methods = cost_methods(item_code, warehouse, batch, serial_number, settings)
    if basis == BASIS_HIGHEST and methods:
        top = max(methods, key=lambda k: methods[k][0])
        return methods[top][0], f"Highest of {', '.join(m.split(' (')[0] for m in methods)}: {methods[top][1]}"
    if basis in methods:
        return methods[basis]
    if methods:           # the chosen method has no data yet: use what the stock is carried at, else the dearest known cost
        top = BASIS_CURRENT if BASIS_CURRENT in methods else max(methods, key=lambda k: methods[k][0])
        return (methods[top][0], methods[top][1]) if basis == BASIS_LAST and top == BASIS_CURRENT else (methods[top][0], f"{methods[top][1]} (no {basis} yet)")
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


def price_row(*, doctype, item_code, customer=None, customer_group=None, currency=None, exchange_rate=1,
              uom=None, conversion_factor=1, quantity=1, discount_percentage=0, discount_amount=0,
              price_basis="Automatic", warehouse=None, batch=None, serial_number=None, settings=None):
    s = settings or _settings()
    currency = currency or base_currency()
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
            currency=(getattr(doc, "currency", None) or base_currency()), exchange_rate=fx,
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


def profit_floor(cost, settings):
    """The lowest rate we may sell at: cost, plus the minimum profit % when one is set (0 = just not below cost)."""
    pct = dec(settings.get("minimum_profit_percent") or 0, "Minimum profit")
    return dec(cost) * (Decimal("1") + pct / Decimal("100")) if pct > 0 else dec(cost)


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
        floor_rate = profit_floor(cost_rate, s)
        if effective_rate + Decimal("0.005") < floor_rate:
            why = f"cost plus the minimum profit of {dec(s.get('minimum_profit_percent'))}%" if floor_rate > cost_rate else "cost"
            problems.append(
                f"Line {index}: {item_code} selling rate after discounts is {money(effective_rate)} in base currency per {getattr(line, 'uom', None) or item.stock_uom}; the lowest allowed is {money(floor_rate)} ({why}; cost {money(cost_rate)}, {source}). Selling below it is blocked."
            )
        line.cost_rate = money(cost_rate / fx)
        line.cost_source = source
    if problems:
        throw("Selling Below Cost: " + "<br>".join(problems))


def explain_item_price(item_code, *, customer=None, customer_group=None, uom=None,
                       conversion_factor=1, currency=None, exchange_rate=1,
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
    methods = cost_methods(item_code, warehouse, batch, serial_number, settings)
    basis_name, basis_from = cost_basis_for(item, settings)
    chosen_price = next((row["price"] for row in candidates if row["basis"] == (info or {}).get("basis_key")), None)
    floor_uom = profit_floor(cost_uom, settings) if cost_uom is not None else None
    narrative = price_narrative(item=item, settings=settings, info=info, cost_stock=cost_stock, cost_uom=cost_uom, factor=factor, fx=fx, currency=currency,
                                uom=selected_uom, methods=methods, basis=basis_name, basis_from=basis_from, price=chosen_price, floor_uom=floor_uom)
    return {
        "narrative": narrative,
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
        "cost_basis": basis_name,
        "cost_basis_from": basis_from,
        "cost_methods": {k: {"cost": money(v[0]), "note": v[1]} for k, v in methods.items()},
        "minimum_profit_percent": settings.get("minimum_profit_percent") or 0,
        "lowest_allowed_per_uom_base": money(floor_uom) if floor_uom is not None else None,
        "candidates": candidates,
        "chosen_price": chosen_price,
    }


def _n(value):
    """1234.5 -> '1,234.50' for reading."""
    return f"{money(value):,.2f}"


def price_narrative(*, item, settings, info, cost_stock, cost_uom, factor, fx, currency, uom, methods, basis, basis_from, price, floor_uom):
    """The price in plain words, step by step, so anyone can follow how it was reached and check it.
    Built on the server so the form, the API and any report tell the same story."""
    code, step = item.name, []
    if info and info.get("source") == "Fixed Item Price":
        step.append(f"{code} has a Fixed Price, so no cost or margin is used: it sells at {_n(info['raw'])} per stock unit.")
    elif cost_stock is None or cost_stock <= 0:
        step.append(f"No cost can be worked out for {code} yet, so no selling price can be built from cost. " + ((info or {}).get("reason") or ""))
        return step
    else:
        step.append(f"1. Cost. The policy is “{basis}” (set at {basis_from}).")
        if methods:
            shown = "; ".join(f"{k.split(' (')[0]} {_n(v[0])}" for k, v in methods.items())
            step.append(f"   Costs available per {item.stock_uom}: {shown}.")
        if basis == BASIS_HIGHEST:
            step.append(f"   “Highest of These” takes the dearest of them so the price cannot fall below any method's cost: {_n(cost_stock)}.")
        else:
            step.append(f"   The cost used is {_n(cost_stock)} per {item.stock_uom} ({(info or {}).get('cost_source') or 'see source'}).")
        if info and info.get("priced") and info.get("candidates"):
            chosen = next((c for c in info["candidates"] if c["key"] == info.get("basis_key")), None)
            how = s_basis = settings.get("selling_price_basis") or "Markup on Cost"
            step.append(f"2. Margin. {info.get('source')} sets {chosen['margin']}% (the order is Customer Group, then Item, then the Inventory Settings default)." if chosen and chosen.get("margin") else "2. Margin. See the candidate prices below.")
            if chosen and chosen.get("margin"):
                m = dec(chosen["margin"])
                if s_basis == "Margin on Selling Price":
                    step.append(f"   Margin on Selling Price: {_n(cost_stock)} ÷ (1 − {m}%) = {_n(info['raw'])}.")
                else:
                    step.append(f"   Markup on Cost: {_n(cost_stock)} × (1 + {m}%) = {_n(info['raw'])}.")
            if info.get("fell_back"):
                step.append(f"   (The {info.get('wanted')} price you asked for is not set, so the next one in the order was used.)")
        elif info:
            step.append("2. Margin. No selling margin is set on the Customer Group, the Item or Inventory Settings, so no price is calculated. " + (info.get("reason") or ""))
    if price is not None:
        conv = []
        if factor != 1:
            conv.append(f"× {factor} for {uom} per {item.stock_uom}")
        if fx != 1:
            conv.append(f"÷ {fx} for {currency}")
        step.append(f"3. Selling unit. " + (f"Price per {uom} in {currency}: " + " ".join(conv) + f" = {_n(price)}" if conv else f"Price per {uom} in {currency}: {_n(price)}")
                    + (f", rounded to the nearest {_n(settings.get('price_rounding_step'))}" if dec(settings.get("price_rounding_step") or 0) > 0 else "") + ".")
        if cost_uom is not None and cost_uom > 0:
            unit_cost = cost_uom / fx
            profit = price - unit_cost
            step.append(f"4. Profit. Cost per {uom} is {_n(unit_cost)} {currency}, so you earn {_n(profit)} per {uom}: {_n(profit / unit_cost * 100)}% on cost, {_n(profit / price * 100) if price else '0.00'}% of the price.")
    if floor_uom is not None:
        pct = dec(settings.get("minimum_profit_percent") or 0)
        step.append(f"{'5' if price is not None else '3'}. Floor. The lowest allowed rate is {_n(floor_uom / fx)} {currency} per {uom}"
                    + (f" (cost plus the minimum profit of {pct}%)" if pct > 0 else " (cost)")
                    + (". Selling below it is blocked." if settings.get("block_selling_below_cost") else ". Blocking below cost is switched off in Inventory Settings, so this is a guide only."))
    return step


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
                currency=request.get("currency") or args.get("currency") or base_currency(),
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
            currency=args.get("currency") or base_currency(), exchange_rate=fx,
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
        floor_rate = profit_floor(cost_per_sales_uom, settings)
        if selling_base + Decimal("0.005") < floor_rate:
            problems.append(
                f"Line {index}: agreed selling rate after discounts is {money(selling_base)} in base currency per {getattr(line, 'uom', None) or item.stock_uom}; the lowest allowed is {money(floor_rate)} (actual warehouse issue cost {money(cost_per_sales_uom)}"
                + (f" plus the minimum profit of {dec(settings.get('minimum_profit_percent'))}%" if floor_rate > cost_per_sales_uom else "") + "). Dispatch below it is blocked."
            )
    if problems:
        throw("Selling Below Cost at Dispatch: " + "<br>".join(problems))
