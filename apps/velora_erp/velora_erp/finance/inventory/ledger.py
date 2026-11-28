"""Append-only stock ledger and inventory valuation services."""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import func, select, update
from velora import db, get_doc, new_doc, throw
from velora.db.tables import get_table
from velora_erp.finance.inventory.valuation import fifo_consume, apply_fifo_value_adjustment, periodic_weighted_average

ZERO = Decimal("0")
QTY = Decimal("0.000001")
MONEY = Decimal("0.01")


def is_stock_item(item_code):
    if not item_code or not db.exists("Inventory Item", item_code):
        return False
    item = get_doc("Inventory Item", item_code)
    return bool(item.is_stock_item and not item.disabled)


def dec(value, label):
    try:
        result = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError):
        throw(f"{label} must be numeric.")
    if not result.is_finite():
        throw(f"{label} must be finite.")
    return result


def money(value):
    return dec(value, "Stock value").quantize(MONEY, rounding=ROUND_HALF_UP)


def _filters(item_code, warehouse, batch=None, serial_number=None):
    t = get_table("Stock Ledger Record")
    conditions = [t.c.item_code == item_code, t.c.warehouse == warehouse]
    conditions.append(t.c.batch == (batch or None))
    conditions.append(t.c.serial_number == (serial_number or None))
    return t, conditions


def assert_not_backdated(item_code, warehouse, batch, serial_number, posting_date):
    t, conditions = _filters(item_code, warehouse, batch, serial_number)
    with db.transaction() as conn:
        latest = conn.execute(select(func.max(t.c.posting_date)).where(*conditions)).scalar()
    if latest and posting_date < latest:
        throw(f"Backdated stock posting is blocked for {item_code} in {warehouse}. Latest stock posting date is {latest}; use that date or a later date.")


def get_stock_balance(item_code, warehouse, batch=None, serial_number=None):
    """Return current quantity, stock value and moving-average cost for one stock key."""
    with db.transaction() as conn:
        t, conditions = _filters(item_code, warehouse, batch, serial_number)
        row = conn.execute(select(
            func.coalesce(func.sum(t.c.actual_qty), 0).label("qty"),
            func.coalesce(func.sum(t.c.stock_value_difference), 0).label("value"),
        ).where(*conditions)).mappings().one()
    qty, value = dec(row["qty"], "Ledger quantity"), dec(row["value"], "Ledger stock value")
    rate = (value / qty) if qty > 0 else ZERO
    return {"qty": qty, "value": money(value), "rate": rate}


def _fifo_layers_from_ledger(item_code, warehouse, batch=None, serial_number=None):
    """Reconstruct remaining FIFO layers from immutable ledger history."""
    t, conditions = _filters(item_code, warehouse, batch, serial_number)
    with db.transaction() as conn:
        rows = conn.execute(select(t).where(*conditions)).mappings().all()
    order = lambda row: (str(row.get("posting_date") or ""), str(row.get("creation") or ""), str(row.get("name") or ""))
    layers = []
    for row in sorted(rows, key=order):
        qty = dec(row.get("actual_qty"), "Stock quantity")
        value = money(row.get("stock_value_difference"))
        if qty > 0:
            if value < 0:
                throw("A FIFO receipt cannot create a negative cost layer.")
            layers.append({"qty": qty, "value": value, "date": row.get("posting_date"), "source": row.get("voucher_no"), "layer_id": row.get("name")})
        elif qty < 0:
            try:
                _, _, layers = fifo_consume(layers, abs(qty))
            except ValueError as exc:
                throw(f"FIFO ledger history is inconsistent for {item_code} in {warehouse}: {exc}")
        elif value:
            try:
                layers = apply_fifo_value_adjustment(layers, value, row.get("valuation_layer_reference"))
            except ValueError as exc:
                throw(f"FIFO value adjustment history is inconsistent for {item_code} in {warehouse}: {exc}")
    return layers


def get_issue_valuation(item, item_code, warehouse, quantity, batch=None, serial_number=None):
    """Return issue cost and method-specific detail for a stock key."""
    qty = dec(quantity, "Issue quantity")
    if qty <= 0:
        throw("Issue quantity must be greater than zero.")
    method = getattr(item, "valuation_method", "Moving Average") or "Moving Average"
    if method == "FIFO":
        layers = _fifo_layers_from_ledger(item_code, warehouse, batch, serial_number)
        try:
            cost, allocations, _ = fifo_consume(layers, qty)
        except ValueError as exc:
            throw(f"Insufficient FIFO stock for {item_code} in {warehouse}: {exc}")
        return {"cost": cost, "rate": cost / qty, "allocations": allocations}
    balance = get_stock_balance(item_code, warehouse, batch, serial_number)
    if balance["qty"] < qty:
        throw(f"Insufficient stock for {item_code}. Available {balance['qty']}, requested {qty}.")
    if balance["rate"] <= 0:
        throw(f"No positive valuation rate exists for {item_code}; cannot issue stock.")
    return {"cost": money(qty * balance["rate"]), "rate": balance["rate"], "allocations": []}


def assert_period_open(item_code, warehouse, posting_date):
    """Prevent movements in a period already finalised by periodic weighted average."""
    try:
        closing = get_table("Inventory Valuation Closing")
    except Exception:
        return
    conditions = [closing.c.docstatus == 1, closing.c.period_start <= posting_date, closing.c.period_end >= posting_date]
    if "warehouse" in closing.c:
        conditions.append((closing.c.warehouse == warehouse) | (closing.c.warehouse.is_(None)))
    row = db.conn().execute(select(closing.c.name).where(*conditions).limit(1)).first()
    if row:
        throw(f"Inventory period is closed by {row[0]}; stock movements dated {posting_date} are blocked.")


def validate_tracking(item, batch=None, serial_number=None, warehouse=None, quantity=None):
    mode = getattr(item, "tracking_mode", "None") or "None"
    if mode == "Serial Number":
        if not serial_number or batch:
            throw(f"{item.name}: select a Serial Number; do not use a Batch on a serial-tracked item.")
        serial = get_doc("Serial Number", serial_number)
        if serial.item_code != item.name or serial.disabled:
            throw(f"Serial Number {serial_number} does not belong to active item {item.name}.")
        if quantity is not None and abs(dec(quantity, "Serial quantity")) not in (ZERO, Decimal("1")):
            throw("Serial-tracked stock must be reconciled one serial number per line (quantity 0 or 1).")
    elif mode == "Batch":
        if not batch or serial_number:
            throw(f"{item.name}: select a Batch; do not use a Serial Number on a batch-tracked item.")
        record = get_doc("Batch", batch)
        if record.item_code != item.name or record.disabled:
            throw(f"Batch {batch} does not belong to active item {item.name}.")
    elif batch or serial_number:
        throw(f"{item.name} is not serial- or batch-tracked; remove the tracking reference.")


def append_stock_ledger(*, posting_date, item_code, warehouse, actual_qty, qty_after, valuation_rate,
                        value_difference, value_after, voucher_type, voucher_no, voucher_detail_no=None,
                        batch=None, serial_number=None, remarks=None, valuation_layer_reference=None):
    record = new_doc(
        "Stock Ledger Record", posting_date=posting_date, item_code=item_code, warehouse=warehouse,
        actual_qty=actual_qty, qty_after_transaction=qty_after, valuation_rate=valuation_rate,
        stock_value_difference=value_difference, stock_value_after_transaction=value_after,
        batch=batch or None, serial_number=serial_number or None, voucher_type=voucher_type,
        voucher_no=voucher_no, voucher_detail_no=voucher_detail_no,
        valuation_layer_reference=valuation_layer_reference or None, remarks=remarks,
    )
    record.flags.inventory_engine_authorized = True
    record.insert(ignore_permissions=True)
    return record


def inventory_settings():
    from velora import get_list
    rows = get_list("Inventory Settings", fields=["name", "default_inventory_asset_account", "goods_received_not_invoiced_account", "cost_of_goods_sold_account", "stock_adjustment_gain_account", "stock_adjustment_loss_account", "purchase_price_variance_account", "opening_balance_clearing_account", "stock_revaluation_gain_account", "stock_revaluation_loss_account"], limit=1, ignore_permissions=True)
    if not rows:
        throw("Create Inventory Settings and configure the inventory, GRNI, COGS and stock adjustment accounts before posting stock transactions.")
    return rows[0]


def _post_inventory_accounting(source, posting_date, currency, exchange_rate, lines, event, remarks):
    from velora_erp.finance.engine import post_financial_transaction
    from velora_erp.finance.source_documents import persist_posting_batch_link
    if not lines:
        return None
    batch = post_financial_transaction(
        source_doctype=source.doctype, source_name=source.name, posting_date=posting_date,
        currency=currency, exchange_rate=exchange_rate, lines=lines,
        posting_event="Adjustment", remarks=remarks or f"Inventory accounting for {source.doctype} {source.name}",
        idempotency_key=f"inventory:{source.doctype}:{source.name}:{event.lower()}",
    )
    link_field = "inventory_posting_batch" if source.meta.get_field("inventory_posting_batch") else "posting_batch"
    if source.meta.get_field(link_field):
        from sqlalchemy import update
        db.conn().execute(update(get_table(source.doctype)).where(get_table(source.doctype).c.name == source.name).values({link_field: batch.name}))
    return batch


def _net_posting_lines(totals, description):
    result = []
    for account, values in totals.items():
        net = money(values[0] - values[1])
        if net > 0:
            result.append({"account": account, "debit": net, "credit": ZERO, "line_description": description})
        elif net < 0:
            result.append({"account": account, "debit": ZERO, "credit": abs(net), "line_description": description})
    return result


def _asset_account(item, settings):
    return getattr(item, "stock_asset_account", None) or settings["default_inventory_asset_account"]


def post_stock_movement(*, source, posting_date, warehouse, lines, direction, rate_field=None, accounting_event=None, remarks=None):
    """Post a source document's stock movement atomically. direction is +1 or -1."""
    if direction not in (-1, 1):
        throw("Stock movement direction must be +1 or -1.")
    stock_lines = [line for line in (lines if lines is not None else (source.lines or [])) if is_stock_item(getattr(line, "item_code", None))]
    if not stock_lines:
        return None
    if not warehouse:
        throw("A Warehouse is required for stock-managed item movements.")
    settings = inventory_settings()
    totals = {}
    with db.transaction() as conn:
        ledger = get_table("Stock Ledger Record")
        duplicate = conn.execute(select(ledger.c.name).where(
            ledger.c.voucher_type == source.doctype, ledger.c.voucher_no == source.name
        ).limit(1)).first()
        if duplicate:
            throw(f"Stock movement for {source.doctype} {source.name} has already been posted.")
        for index, line in enumerate(lines if lines is not None else (source.lines or []), 1):
            if not is_stock_item(getattr(line, "item_code", None)):
                continue
            item = get_doc("Inventory Item", line.item_code)
            if item.disabled:
                throw(f"Line {index}: {item.name} is disabled.")
            conversion_factor = dec(getattr(line, "conversion_factor", 1) or 1, f"Line {index} conversion factor")
            if conversion_factor <= 0:
                throw(f"Line {index}: Stock UOM Conversion Factor must be greater than zero.")
            qty = dec(line.quantity, f"Line {index} quantity") * conversion_factor * direction
            if qty == 0:
                throw(f"Line {index}: stock movement quantity must not be zero.")
            batch = getattr(line, "batch", None) or None
            serial = getattr(line, "serial_number", None) or None
            validate_tracking(item, batch, serial, warehouse, qty)
            assert_period_open(item.name, warehouse, posting_date)
            assert_not_backdated(item.name, warehouse, batch, serial, posting_date)
            balance = get_stock_balance(item.name, warehouse, batch, serial)
            new_qty = (balance["qty"] + qty).quantize(QTY, rounding=ROUND_HALF_UP)
            if new_qty < 0:
                throw(f"Line {index}: insufficient stock for {item.name}. Available {balance['qty']}, requested {abs(qty)}.")
            if direction < 0:
                from velora_erp.finance.inventory import reservations, expiry
                reservations.assert_unreserved(source, item.name, warehouse, batch, abs(qty))
                expiry.assert_not_expired(source, item.name, batch)
            if direction > 0:
                entered_rate = dec(getattr(line, rate_field, None) if rate_field else None, "Receipt valuation rate")
                if entered_rate > 0:
                    rate = entered_rate * dec(getattr(source, "exchange_rate", 1) or 1, "Exchange Rate") / conversion_factor
                else:
                    rate = dec(item.standard_rate, "Item standard rate")
                if rate <= 0:
                    throw(f"Line {index}: enter a positive valuation rate for {item.name}.")
            else:
                issue = get_issue_valuation(item, item.name, warehouse, abs(qty), batch, serial)
                rate = issue["rate"]
                # Persist the actual issue valuation on the operational line. This is
                # the realised COGS evidence used by Sales Margin Analysis, not a later estimate.
                if source.doctype == "Delivery Note":
                    line.issue_cost_rate = rate
                    line.issue_cost_amount = money(issue["cost"])
                    # on_submit runs after the parent document's first write. Persist
                    # the valuation snapshot explicitly within this same transaction.
                    child_table = get_table("Delivery Note Line")
                    db.conn().execute(update(child_table).where(child_table.c.name == line.name).values(
                        issue_cost_rate=money(rate), issue_cost_amount=money(issue["cost"])))
                if source.doctype == "Sales Invoice":
                    fx = dec(getattr(source, "exchange_rate", 1) or 1, "Exchange Rate")
                    line_rate = (rate * conversion_factor / fx).quantize(Decimal("0.000001"))
                    line.valuation_rate = line_rate
                    child_table = get_table("Sales Invoice Line")
                    db.conn().execute(update(child_table).where(child_table.c.name == line.name).values(valuation_rate=line_rate))
            value_diff = money(qty * rate)
            new_value = money(balance["value"] + value_diff)
            new_rate = (new_value / new_qty) if new_qty > 0 else ZERO
            append_stock_ledger(
                posting_date=posting_date, item_code=item.name, warehouse=warehouse,
                actual_qty=qty, qty_after=new_qty, valuation_rate=new_rate,
                value_difference=value_diff, value_after=new_value, voucher_type=source.doctype,
                voucher_no=source.name, voucher_detail_no=getattr(line, "name", None),
                batch=batch, serial_number=serial, remarks=remarks,
            )
            if direction < 0:
                from velora_erp.finance.inventory import reservations
                reservations.consume(source, item.name, warehouse, batch, abs(qty))
            if serial:
                serial_doc = get_doc("Serial Number", serial)
                if direction < 0:
                    if serial_doc.status != "Available" or (serial_doc.warehouse and serial_doc.warehouse != warehouse):
                        throw(f"Serial Number {serial} is not available in Warehouse {warehouse}.")
                    serial_doc.status = "Returned" if source.doctype == "Purchase Return" else "Delivered"
                    serial_doc.warehouse = None
                else:
                    if serial_doc.warehouse and serial_doc.warehouse != warehouse:
                        throw(f"Serial Number {serial} is recorded in another Warehouse.")
                    serial_doc.status = "Available"
                    serial_doc.warehouse = warehouse
                serial_doc.save(ignore_permissions=True)
            asset = _asset_account(item, settings)
            amount = abs(value_diff)
            if accounting_event == "Purchase Receipt":
                debit, credit = asset, settings["goods_received_not_invoiced_account"]
            elif accounting_event == "Delivery Note":
                debit, credit = settings["cost_of_goods_sold_account"], asset
            elif accounting_event == "Sales Return":
                debit, credit = asset, settings["cost_of_goods_sold_account"]
            elif accounting_event == "Purchase Return":
                # The financial return already credited the item's inventory account at the invoice price (as a debit note does in
                # ERPNext). Here only the difference between that price and the cost actually removed from stock is moved, so the
                # inventory account ends up reduced by the stock cost and the remainder is a purchase price variance.
                invoiced = money(dec(getattr(line, "amount", 0), f"Line {index} amount") * dec(getattr(source, "exchange_rate", 1) or 1, "Exchange Rate"))
                diff = invoiced - amount
                ppv = settings.get("purchase_price_variance_account")
                if diff and not ppv:
                    throw("Configure Purchase Price Variance Account in Inventory Settings before returning stock items.")
                if diff > 0:
                    debit, credit, amount = asset, ppv, diff
                elif diff < 0:
                    debit, credit, amount = ppv, asset, -diff
                else:
                    debit = credit = None
            else:
                debit = credit = None
            if debit and amount:
                totals.setdefault(debit, [ZERO, ZERO])[0] += amount
                totals.setdefault(credit, [ZERO, ZERO])[1] += amount
        if accounting_event and totals:
            from velora import get_list
            finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
            if not finance: throw("Finance Settings must be configured before inventory posting.")
            _post_inventory_accounting(source, posting_date, finance[0]["base_currency"], 1,
                _net_posting_lines(totals, f"Inventory {accounting_event}"), "Adjustment", remarks)


def calculate_reconciliation_values(system_qty, system_value, physical_qty, proposed_rate, shortage_value=None):
    system_qty = dec(system_qty, "Current Stock Balance")
    system_value = money(system_value)
    physical_qty = dec(physical_qty, "Physical Count")
    proposed_rate = dec(proposed_rate, "Proposed Price")
    if physical_qty < 0 or proposed_rate < 0:
        throw("Physical Count and Proposed Price cannot be negative.")
    current_rate = (system_value / system_qty) if system_qty > 0 else ZERO
    adjustment_qty = (physical_qty - system_qty).quantize(QTY, rounding=ROUND_HALF_UP)
    if adjustment_qty > 0 and proposed_rate <= 0:
        throw("Proposed Price must be greater than zero when the physical count increases stock.")
    # Positive variances use the proposed price. Shortages remove stock at its current
    # moving-average cost. A count with no quantity variance does not revalue existing stock.
    adjustment_rate = proposed_rate if adjustment_qty > 0 else current_rate
    adjustment_value = money(adjustment_qty * adjustment_rate)
    if adjustment_qty < 0 and shortage_value is not None:
        adjustment_value = -money(shortage_value)
        adjustment_rate = abs(adjustment_value / adjustment_qty) if adjustment_qty else ZERO
    new_value = money(system_value + adjustment_value)
    new_rate = (new_value / physical_qty) if physical_qty > 0 else ZERO
    return {
        "adjustment_qty": adjustment_qty,
        "adjustment_value": adjustment_value,
        "new_stock_value": new_value,
        "new_valuation_rate": new_rate,
        "current_cost": current_rate,
        "adjustment_rate": adjustment_rate,
    }


def prepare_reconciliation(doc):
    if not doc.posting_date or not doc.warehouse:
        throw("Posting Date and Warehouse are required.")
    warehouse = get_doc("Warehouse", doc.warehouse)
    if warehouse.disabled or warehouse.is_group:
        throw("Select an active leaf Warehouse for stock reconciliation.")
    if not doc.items:
        throw("Add at least one item to the stock count.")
    seen = set(); total_qty = ZERO; total_value = ZERO
    for index, line in enumerate(doc.items, 1):
        if not line.item_code:
            throw(f"Line {index}: Inventory Item is required.")
        item = get_doc("Inventory Item", line.item_code)
        if item.disabled or not item.is_stock_item:
            throw(f"Line {index}: select an active stock item.")
        batch = getattr(line, "batch", None) or None
        serial = getattr(line, "serial_number", None) or None
        key = (item.name, batch, serial)
        if key in seen:
            throw(f"Line {index}: duplicate item/tracking combination in this reconciliation.")
        seen.add(key)
        physical = dec(line.physical_qty, f"Line {index} Physical Count")
        if physical < 0:
            throw(f"Line {index}: Physical Count cannot be negative.")
        validate_tracking(item, batch, serial, doc.warehouse, physical)
        assert_period_open(item.name, doc.warehouse, doc.posting_date)
        assert_not_backdated(item.name, doc.warehouse, batch, serial, doc.posting_date)
        balance = get_stock_balance(item.name, doc.warehouse, batch, serial)
        proposed = dec(line.proposed_rate, f"Line {index} Proposed Price")
        shortage_cost = None
        if physical < balance["qty"] and getattr(item, "valuation_method", "Moving Average") == "FIFO":
            shortage_cost = get_issue_valuation(item, item.name, doc.warehouse, balance["qty"] - physical, batch, serial)["cost"]
        calculated = calculate_reconciliation_values(balance["qty"], balance["value"], physical, proposed, shortage_cost)
        variance = calculated["adjustment_qty"]
        target_value = calculated["new_stock_value"]
        value_diff = calculated["adjustment_value"]
        line.system_qty = balance["qty"]
        line.adjustment_qty = variance
        line.current_cost = balance["rate"]
        line.current_stock_value = balance["value"]
        line.adjustment_value = value_diff
        line.description = line.description or item.item_name
        total_qty += variance; total_value += value_diff
    doc.total_quantity_difference = total_qty
    doc.total_value_difference = money(total_value)


def submit_reconciliation(doc):
    from velora_erp.finance.source_documents import ensure_approved
    ensure_approved(doc, required=True)
    # The reconciliation itself is submitted in a transaction. Every ledger write joins it.
    ledger = get_table("Stock Ledger Record")
    existing = db.conn().execute(select(ledger.c.name).where(
        ledger.c.voucher_type == doc.doctype, ledger.c.voucher_no == doc.name
    ).limit(1)).first()
    if existing:
        throw("Stock Reconciliation has already generated stock ledger records.")
    settings = inventory_settings()
    financial = {}
    for index, line in enumerate(doc.items, 1):
        item = get_doc("Inventory Item", line.item_code)
        batch = getattr(line, "batch", None) or None
        serial = getattr(line, "serial_number", None) or None
        assert_period_open(item.name, doc.warehouse, doc.posting_date)
        assert_not_backdated(item.name, doc.warehouse, batch, serial, doc.posting_date)
        balance = get_stock_balance(item.name, doc.warehouse, batch, serial)
        physical = dec(line.physical_qty, f"Line {index} Physical Count")
        proposed = dec(line.proposed_rate, f"Line {index} Proposed Price")
        shortage_cost = None
        if physical < balance["qty"] and getattr(item, "valuation_method", "Moving Average") == "FIFO":
            shortage_cost = get_issue_valuation(item, item.name, doc.warehouse, balance["qty"] - physical, batch, serial)["cost"]
        calculated = calculate_reconciliation_values(balance["qty"], balance["value"], physical, proposed, shortage_cost)
        variance = calculated["adjustment_qty"]
        target_value = calculated["new_stock_value"]
        value_diff = calculated["adjustment_value"]
        # A zero-quantity valuation adjustment is valid; it changes cost without changing units.
        new_rate = calculated["new_valuation_rate"]
        if variance != 0 or value_diff != 0:
            append_stock_ledger(
                posting_date=doc.posting_date, item_code=item.name, warehouse=doc.warehouse,
                actual_qty=variance, qty_after=physical, valuation_rate=new_rate,
                value_difference=value_diff, value_after=target_value,
                voucher_type=doc.doctype, voucher_no=doc.name,
                voucher_detail_no=getattr(line, "name", None), batch=batch, serial_number=serial,
                remarks=f"Stock Reconciliation {doc.name}: {doc.remarks or 'Physical stock count adjustment'}",
            )
        if serial:
            serial_doc = get_doc("Serial Number", serial)
            if physical > 0:
                if serial_doc.warehouse and serial_doc.warehouse != doc.warehouse:
                    throw(f"Serial Number {serial} is recorded in another Warehouse.")
                serial_doc.status = "Available"; serial_doc.warehouse = doc.warehouse
            else:
                serial_doc.status = "Scrapped"; serial_doc.warehouse = None
            serial_doc.save(ignore_permissions=True)
        asset = _asset_account(item, settings)
        if value_diff > 0:
            debit, credit = asset, settings["stock_adjustment_gain_account"]
        elif value_diff < 0:
            debit, credit = settings["stock_adjustment_loss_account"], asset
        else:
            debit = credit = None
        if debit:
            financial.setdefault(debit, [ZERO, ZERO])[0] += abs(value_diff)
            financial.setdefault(credit, [ZERO, ZERO])[1] += abs(value_diff)
    if financial:
        from velora import get_list
        finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not finance: throw("Finance Settings must be configured before posting stock adjustments.")
        batch = _post_inventory_accounting(doc, doc.posting_date, finance[0]["base_currency"], 1,
            _net_posting_lines(financial, "Stock reconciliation valuation adjustment"), "Adjustment", doc.remarks)
        if batch:
            from sqlalchemy import update
            source_table = get_table(doc.doctype)
            db.conn().execute(update(source_table).where(source_table.c.name == doc.name).values(inventory_posting_batch=batch.name))


def capitalize_landed_cost(doc):
    """Increase inventory value from a submitted receipt and post the reclassification."""
    from velora_erp.finance.engine import post_financial_transaction
    from velora_erp.finance.source_documents import ensure_approved, persist_posting_batch_link
    ensure_approved(doc, required=True)
    receipt = get_doc("Purchase Receipt", doc.purchase_receipt)
    settings = inventory_settings()
    ledger = get_table("Stock Ledger Record")
    duplicate = db.conn().execute(select(ledger.c.name).where(
        ledger.c.voucher_type == doc.doctype, ledger.c.voucher_no == doc.name
    ).limit(1)).first()
    if duplicate:
        throw("Landed Cost Voucher has already been capitalised into inventory.")
    receipt_lines = {str(getattr(row, "name", "")): row for row in receipt.lines or []}
    financial = {}
    for index, allocation in enumerate(doc.allocations, 1):
        source_line = receipt_lines.get(str(allocation.source_line or ""))
        if not source_line:
            throw(f"Allocation {index}: source Purchase Receipt line no longer exists.")
        item = get_doc("Inventory Item", source_line.item_code)
        batch = getattr(source_line, "batch", None) or None
        serial = getattr(source_line, "serial_number", None) or None
        assert_period_open(item.name, receipt.warehouse, doc.voucher_date)
        assert_not_backdated(item.name, receipt.warehouse, batch, serial, doc.voucher_date)
        balance = get_stock_balance(item.name, receipt.warehouse, batch, serial)
        receipt_factor = dec(getattr(source_line, "conversion_factor", 1) or 1, f"Allocation {index} receipt conversion factor")
        received_qty = dec(source_line.quantity, f"Allocation {index} received quantity") * receipt_factor
        if receipt_factor <= 0 or received_qty <= 0 or balance["qty"] < 0:
            throw(f"Allocation {index}: invalid received or on-hand quantity for {item.name}.")
        amount = money(dec(allocation.allocated_amount, "Allocated landed cost") * dec(doc.exchange_rate, "Exchange Rate"))
        if amount <= 0:
            throw(f"Allocation {index}: allocated landed cost must be positive.")
        # Allocate landed cost between the quantity still on hand and the quantity
        # already consumed. The consumed portion adjusts COGS, not closing inventory.
        valuation_layer_reference = None
        if getattr(item, "valuation_method", "Moving Average") == "FIFO":
            receipt_ledger = db.conn().execute(select(ledger.c.name).where(
                ledger.c.voucher_type == "Purchase Receipt", ledger.c.voucher_no == receipt.name,
                ledger.c.voucher_detail_no == str(source_line.name), ledger.c.item_code == item.name,
                ledger.c.warehouse == receipt.warehouse, ledger.c.batch == batch,
                ledger.c.serial_number == serial, ledger.c.actual_qty > 0,
            ).order_by(ledger.c.posting_date, ledger.c.name).limit(1)).first()
            if not receipt_ledger:
                throw(f"Allocation {index}: original FIFO receipt layer was not found for {item.name}.")
            valuation_layer_reference = receipt_ledger[0]
            layers = _fifo_layers_from_ledger(item.name, receipt.warehouse, batch, serial)
            original_layer = next((layer for layer in layers if layer.get("layer_id") == valuation_layer_reference), None)
            eligible_on_hand = original_layer["qty"] if original_layer else ZERO
        else:
            eligible_on_hand = min(balance["qty"], received_qty)
        inventory_amount = money(amount * eligible_on_hand / received_qty)
        consumed_amount = money(amount - inventory_amount)
        if inventory_amount > 0:
            new_value = money(balance["value"] + inventory_amount)
            new_rate = new_value / balance["qty"]
            append_stock_ledger(
                posting_date=doc.voucher_date, item_code=item.name, warehouse=receipt.warehouse,
                actual_qty=ZERO, qty_after=balance["qty"], valuation_rate=new_rate,
                value_difference=inventory_amount, value_after=new_value, voucher_type=doc.doctype,
                voucher_no=doc.name, voucher_detail_no=getattr(allocation, "name", None),
                batch=batch, serial_number=serial, valuation_layer_reference=valuation_layer_reference,
                remarks=f"Landed cost capitalisation from {doc.name}",
            )
        asset = _asset_account(item, settings)
        financial.setdefault(asset, [ZERO, ZERO])[0] += inventory_amount
        financial.setdefault(settings["cost_of_goods_sold_account"], [ZERO, ZERO])[0] += consumed_amount
        # Charge-account credits are added below, after allocation debits have been calculated.
    debit_total = sum((values[0] for values in financial.values()), ZERO)
    converted_charges = []
    assigned = ZERO
    for index, charge in enumerate(doc.charges, 1):
        if index == len(doc.charges):
            base_amount = money(debit_total - assigned)
        else:
            base_amount = money(dec(charge.amount, "Charge Amount") * dec(doc.exchange_rate, "Exchange Rate"))
            assigned += base_amount
        converted_charges.append((charge.charge_account, base_amount))
    for account, amount in converted_charges:
        financial.setdefault(account, [ZERO, ZERO])[1] += amount
    credit_total = sum((values[1] for values in financial.values()), ZERO)
    if debit_total != credit_total:
        throw(f"Landed cost accounting is not balanced after currency conversion: debit {debit_total}, credit {credit_total}.")
    from velora import get_list
    finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
    if not finance:
        throw("Finance Settings must be configured before landed cost capitalization.")
    batch = post_financial_transaction(
        source_doctype=doc.doctype, source_name=doc.name, posting_date=doc.voucher_date,
        currency=finance[0]["base_currency"], exchange_rate=1,
        lines=_net_posting_lines(financial, "Landed cost capitalisation"),
        posting_event="Adjustment", remarks=doc.narration,
        idempotency_key=f"landed-cost:{doc.name}:capitalization",
    )
    persist_posting_batch_link(doc, batch)
    return batch


def post_stock_transfer(source, *, source_warehouse=None, target_warehouse=None, lines=None):
    """Move stock between warehouses at the source warehouse's carrying cost.

    A transfer creates paired immutable quantity/value records and never creates
    revenue, expense or a second inventory asset posting.

    `source_warehouse`, `target_warehouse` and `lines` default to the document's own. A two-step transfer calls this twice:
    source -> transit when the transfer is submitted, then transit -> destination when each Stock Transfer Receipt is.
    """
    from velora_erp.finance.source_documents import ensure_approved
    ensure_approved(source, required=True)
    from_wh = source_warehouse or source.source_warehouse
    to_wh = target_warehouse or source.target_warehouse
    rows = list(lines if lines is not None else (source.lines or []))
    source_warehouse = get_doc("Warehouse", from_wh)
    target_warehouse = get_doc("Warehouse", to_wh)
    # Warehouse row locks serialize movements touching the same stock locations.
    for warehouse_doc in sorted((source_warehouse, target_warehouse), key=lambda x: x.name):
        warehouse_doc._lock_and_check()
    if source_warehouse.disabled or source_warehouse.is_group or target_warehouse.disabled or target_warehouse.is_group:
        throw("Stock Transfer requires active leaf source and destination warehouses.")
    if from_wh == to_wh:
        throw("Source and destination warehouses must be different.")
    if not rows:
        throw("Add at least one Stock Transfer line.")
    ledger = get_table("Stock Ledger Record")
    duplicate = db.conn().execute(select(ledger.c.name).where(
        ledger.c.voucher_type == source.doctype, ledger.c.voucher_no == source.name
    ).limit(1)).first()
    if duplicate:
        throw("Stock Transfer has already created Stock Ledger Records.")
    seen = set()
    with db.transaction():
        for index, line in enumerate(rows, 1):
            item = get_doc("Inventory Item", line.item_code)
            if item.disabled or not item.is_stock_item:
                throw(f"Line {index}: select an active stock item.")
            qty = dec(line.quantity, f"Line {index} Transfer Quantity")
            if qty <= 0:
                throw(f"Line {index}: Transfer Quantity must be greater than zero.")
            batch = getattr(line, "batch", None) or None
            serial = getattr(line, "serial_number", None) or None
            validate_tracking(item, batch, serial, from_wh, qty)
            assert_period_open(item.name, from_wh, source.posting_date)
            assert_period_open(item.name, to_wh, source.posting_date)
            key = (item.name, batch, serial)
            if key in seen:
                throw(f"Line {index}: duplicate item/batch/serial combination.")
            seen.add(key)
            assert_not_backdated(item.name, from_wh, batch, serial, source.posting_date)
            assert_not_backdated(item.name, to_wh, batch, serial, source.posting_date)
            from_balance = get_stock_balance(item.name, from_wh, batch, serial)
            if from_balance["qty"] < qty:
                throw(f"Line {index}: insufficient stock in {from_wh}. Available {from_balance['qty']}; requested {qty}.")
            from velora_erp.finance.inventory import reservations, expiry
            reservations.assert_unreserved(source, item.name, from_wh, batch, qty)
            expiry.assert_not_expired(source, item.name, batch, to_warehouse=to_wh)
            issue = get_issue_valuation(item, item.name, from_wh, qty, batch, serial)
            value = issue["cost"]
            rate = issue["rate"]
            to_balance = get_stock_balance(item.name, to_wh, batch, serial)
            from_qty = (from_balance["qty"] - qty).quantize(QTY, rounding=ROUND_HALF_UP)
            from_value = money(from_balance["value"] - value)
            from_rate = from_value / from_qty if from_qty > 0 else ZERO
            append_stock_ledger(
                posting_date=source.posting_date, item_code=item.name, warehouse=from_wh,
                actual_qty=-qty, qty_after=from_qty, valuation_rate=from_rate,
                value_difference=-value, value_after=from_value, voucher_type=source.doctype,
                voucher_no=source.name, voucher_detail_no=getattr(line, "name", None),
                batch=batch, serial_number=serial, remarks=f"Transfer to {to_wh}",
            )
            # Preserve individual FIFO layer costs at the destination rather than
            # collapsing several source layers into one blended receipt layer.
            target_allocations = issue["allocations"] or [{"qty": qty, "value": value, "rate": rate}]
            to_qty = to_balance["qty"]
            to_value = to_balance["value"]
            for allocation in target_allocations:
                layer_qty = dec(allocation["qty"], "Transfer layer quantity")
                layer_value = money(allocation["value"])
                to_qty = (to_qty + layer_qty).quantize(QTY, rounding=ROUND_HALF_UP)
                to_value = money(to_value + layer_value)
                to_rate = to_value / to_qty if to_qty > 0 else ZERO
                append_stock_ledger(
                    posting_date=source.posting_date, item_code=item.name, warehouse=to_wh,
                    actual_qty=layer_qty, qty_after=to_qty, valuation_rate=dec(allocation.get("rate"), "Transfer layer rate"),
                    value_difference=layer_value, value_after=to_value, voucher_type=source.doctype,
                    voucher_no=source.name, voucher_detail_no=getattr(line, "name", None),
                    batch=batch, serial_number=serial, remarks=f"Transfer from {from_wh}",
                )
            if serial:
                serial_doc = get_doc("Serial Number", serial)
                if serial_doc.status != "Available" or serial_doc.warehouse != from_wh:
                    throw(f"Serial Number {serial} is not available in source Warehouse {from_wh}.")
                serial_doc.warehouse = to_wh
                serial_doc.save(ignore_permissions=True)
            reservations.consume(source, item.name, from_wh, batch, qty)
    return True


def get_stock_balances(*, item_code=None, warehouse=None, batch=None, serial_number=None):
    """Return grouped on-hand quantity and carrying value from the stock ledger."""
    from sqlalchemy import and_
    t = get_table("Stock Ledger Record")
    conditions = []
    if item_code: conditions.append(t.c.item_code == item_code)
    if warehouse: conditions.append(t.c.warehouse == warehouse)
    if batch: conditions.append(t.c.batch == batch)
    if serial_number: conditions.append(t.c.serial_number == serial_number)
    stmt = select(
        t.c.item_code, t.c.warehouse, t.c.batch, t.c.serial_number,
        func.sum(t.c.actual_qty).label("qty"),
        func.sum(t.c.stock_value_difference).label("stock_value"),
    ).group_by(t.c.item_code, t.c.warehouse, t.c.batch, t.c.serial_number)
    if conditions: stmt = stmt.where(*conditions)
    with db.transaction() as conn:
        rows = conn.execute(stmt).mappings().all()
    result = []
    for row in rows:
        qty = dec(row["qty"], "Stock quantity")
        value = money(row["stock_value"])
        result.append({"item_code": row["item_code"], "warehouse": row["warehouse"], "batch": row["batch"],
                       "serial_number": row["serial_number"], "qty": qty, "stock_value": value,
                       "valuation_rate": value / qty if qty > 0 else ZERO})
    return result



def prepare_stock_revaluation(doc):
    if not doc.posting_date or not doc.items:
        throw("Posting Date and at least one Stock Revaluation line are required.")
    seen = set()
    total = ZERO
    for index, line in enumerate(doc.items, 1):
        item = get_doc("Inventory Item", line.item_code)
        if item.disabled or not item.is_stock_item:
            throw(f"Line {index}: select an active stock item.")
        warehouse = get_doc("Warehouse", line.warehouse)
        if warehouse.disabled or warehouse.is_group:
            throw(f"Line {index}: select an active leaf Warehouse.")
        batch = getattr(line, "batch", None) or None
        serial = getattr(line, "serial_number", None) or None
        key = (item.name, line.warehouse, batch, serial)
        if key in seen:
            throw(f"Line {index}: duplicate item/warehouse/batch/serial combination.")
        seen.add(key)
        validate_tracking(item, batch, serial, line.warehouse)
        balance = get_stock_balance(item.name, line.warehouse, batch, serial)
        if balance["qty"] <= 0:
            throw(f"Line {index}: cannot revalue {item.name}; there is no positive stock on hand.")
        proposed = dec(line.proposed_rate, f"Line {index} Proposed Valuation Rate")
        if proposed < 0:
            throw(f"Line {index}: Proposed Valuation Rate cannot be negative.")
        target = money(balance["qty"] * proposed)
        difference = money(target - balance["value"])
        line.current_qty = balance["qty"]
        line.current_value = balance["value"]
        line.current_rate = balance["rate"]
        line.proposed_value = target
        line.value_difference = difference
        total += difference
    doc.total_value_difference = money(total)


def submit_stock_revaluation(doc):
    from velora_erp.finance.source_documents import ensure_approved
    ensure_approved(doc, required=True)
    ledger = get_table("Stock Ledger Record")
    duplicate = db.conn().execute(select(ledger.c.name).where(
        ledger.c.voucher_type == doc.doctype, ledger.c.voucher_no == doc.name
    ).limit(1)).first()
    if duplicate:
        throw("Stock Revaluation has already created Stock Ledger Records.")
    settings = inventory_settings()
    financial = {}
    for index, line in enumerate(doc.items, 1):
        item = get_doc("Inventory Item", line.item_code)
        batch = getattr(line, "batch", None) or None
        serial = getattr(line, "serial_number", None) or None
        assert_period_open(item.name, line.warehouse, doc.posting_date)
        assert_not_backdated(item.name, line.warehouse, batch, serial, doc.posting_date)
        balance = get_stock_balance(item.name, line.warehouse, batch, serial)
        proposed = dec(line.proposed_rate, f"Line {index} Proposed Valuation Rate")
        target = money(balance["qty"] * proposed)
        difference = money(target - balance["value"])
        if difference == 0:
            continue
        if getattr(item, "valuation_method", "Moving Average") == "FIFO":
            layers = _fifo_layers_from_ledger(item.name, line.warehouse, batch, serial)
            try:
                apply_fifo_value_adjustment(layers, difference)
            except ValueError as exc:
                throw(f"Line {index}: {exc}")
        append_stock_ledger(
            posting_date=doc.posting_date, item_code=item.name, warehouse=line.warehouse,
            actual_qty=ZERO, qty_after=balance["qty"], valuation_rate=proposed,
            value_difference=difference, value_after=target, voucher_type=doc.doctype,
            voucher_no=doc.name, voucher_detail_no=getattr(line, "name", None),
            batch=batch, serial_number=serial, remarks=doc.remarks or "Approved stock revaluation",
        )
        asset = _asset_account(item, settings)
        gain = settings.get("stock_revaluation_gain_account") or settings["stock_adjustment_gain_account"]
        loss = settings.get("stock_revaluation_loss_account") or settings["stock_adjustment_loss_account"]
        if difference > 0:
            financial.setdefault(asset, [ZERO, ZERO])[0] += difference
            financial.setdefault(gain, [ZERO, ZERO])[1] += difference
        else:
            financial.setdefault(loss, [ZERO, ZERO])[0] += abs(difference)
            financial.setdefault(asset, [ZERO, ZERO])[1] += abs(difference)
    if financial:
        from velora import get_list
        finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not finance:
            throw("Finance Settings must be configured before stock revaluation.")
        batch = _post_inventory_accounting(doc, doc.posting_date, finance[0]["base_currency"], 1,
            _net_posting_lines(financial, "Stock revaluation"), "Revaluation", doc.remarks)
        if batch:
            from sqlalchemy import update
            db.conn().execute(update(get_table(doc.doctype)).where(get_table(doc.doctype).c.name == doc.name).values(inventory_posting_batch=batch.name))


def post_opening_stock_entry(doc):
    from velora_erp.finance.source_documents import ensure_approved
    ensure_approved(doc, required=True)
    settings = inventory_settings()
    clearing = settings.get("opening_balance_clearing_account")
    if not clearing:
        throw("Configure Opening Stock Clearing Account in Inventory Settings before posting opening stock.")
    ledger = get_table("Stock Ledger Record")
    duplicate = db.conn().execute(select(ledger.c.name).where(
        ledger.c.voucher_type == doc.doctype, ledger.c.voucher_no == doc.name
    ).limit(1)).first()
    if duplicate:
        throw("Opening Stock Entry has already created Stock Ledger Records.")
    financial = {}
    seen = set()
    for index, line in enumerate(doc.items, 1):
        item = get_doc("Inventory Item", line.item_code)
        warehouse = get_doc("Warehouse", line.warehouse)
        if item.disabled or not item.is_stock_item:
            throw(f"Line {index}: select an active stock item.")
        if warehouse.disabled or warehouse.is_group:
            throw(f"Line {index}: select an active leaf Warehouse.")
        qty = dec(line.quantity, f"Line {index} Opening Quantity")
        rate = dec(line.valuation_rate, f"Line {index} Opening Valuation Rate")
        if qty <= 0 or rate <= 0:
            throw(f"Line {index}: Opening Quantity and Valuation Rate must be greater than zero.")
        batch = getattr(line, "batch", None) or None
        serial = getattr(line, "serial_number", None) or None
        validate_tracking(item, batch, serial, warehouse.name, qty)
        key = (item.name, warehouse.name, batch, serial)
        if key in seen:
            throw(f"Line {index}: duplicate item/warehouse/batch/serial combination.")
        seen.add(key)
        assert_period_open(item.name, warehouse.name, doc.posting_date)
        assert_not_backdated(item.name, warehouse.name, batch, serial, doc.posting_date)
        balance = get_stock_balance(item.name, warehouse.name, batch, serial)
        prior_table, prior_conditions = _filters(item.name, warehouse.name, batch, serial)
        prior_movement = db.conn().execute(select(prior_table.c.name).where(*prior_conditions).limit(1)).first()
        if prior_movement or balance["qty"] != 0 or balance["value"] != 0:
            throw(f"Line {index}: Opening Stock Entry is only permitted before any stock ledger movement exists for {item.name} in {warehouse.name}.")
        value = money(qty * rate)
        append_stock_ledger(
            posting_date=doc.posting_date, item_code=item.name, warehouse=warehouse.name,
            actual_qty=qty, qty_after=qty, valuation_rate=rate, value_difference=value,
            value_after=value, voucher_type=doc.doctype, voucher_no=doc.name,
            voucher_detail_no=getattr(line, "name", None), batch=batch, serial_number=serial,
            remarks=doc.remarks or "Opening inventory balance",
        )
        line.amount = value
        asset = _asset_account(item, settings)
        financial.setdefault(asset, [ZERO, ZERO])[0] += value
        financial.setdefault(clearing, [ZERO, ZERO])[1] += value
        if serial:
            serial_doc = get_doc("Serial Number", serial)
            if serial_doc.warehouse and serial_doc.warehouse != warehouse.name:
                throw(f"Serial Number {serial} is recorded in another Warehouse.")
            serial_doc.status = "Available"
            serial_doc.warehouse = warehouse.name
            serial_doc.save(ignore_permissions=True)
    if financial:
        from velora import get_list
        finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not finance:
            throw("Finance Settings must be configured before opening stock posting.")
        batch = _post_inventory_accounting(doc, doc.posting_date, finance[0]["base_currency"], 1,
            _net_posting_lines(financial, "Opening stock balances"), "Opening", doc.remarks)
        if batch:
            from sqlalchemy import update
            db.conn().execute(update(get_table(doc.doctype)).where(get_table(doc.doctype).c.name == doc.name).values(inventory_posting_batch=batch.name))


def close_weighted_average_period(doc):
    """Finalise periodic weighted average for all eligible stock keys in scope."""
    from velora_erp.finance.source_documents import ensure_approved
    ensure_approved(doc, required=True)
    if not doc.period_start or not doc.period_end or doc.period_start > doc.period_end:
        throw("A valid Period Start and Period End are required.")
    if doc.posting_date != doc.period_end:
        throw("Weighted Average Closing Posting Date must equal Period End.")
    closing_table = get_table("Inventory Valuation Closing")
    overlap_conditions = [
        closing_table.c.docstatus == 1,
        closing_table.c.name != doc.name,
        closing_table.c.period_start <= doc.period_end,
        closing_table.c.period_end >= doc.period_start,
    ]
    if doc.warehouse:
        overlap_conditions.append((closing_table.c.warehouse == doc.warehouse) | (closing_table.c.warehouse.is_(None)))
    # A company-wide close conflicts with any warehouse-specific close in the same period.
    duplicate = db.conn().execute(select(closing_table.c.name).where(*overlap_conditions).limit(1)).first()
    if duplicate:
        throw(f"This inventory period has already been closed by {duplicate[0]}.")
    ledger = get_table("Stock Ledger Record")
    key_stmt = select(ledger.c.item_code, ledger.c.warehouse, ledger.c.batch, ledger.c.serial_number).where(
        ledger.c.posting_date >= doc.period_start, ledger.c.posting_date <= doc.period_end
    )
    if doc.warehouse:
        key_stmt = key_stmt.where(ledger.c.warehouse == doc.warehouse)
    key_stmt = key_stmt.group_by(ledger.c.item_code, ledger.c.warehouse, ledger.c.batch, ledger.c.serial_number)
    keys = db.conn().execute(key_stmt).mappings().all()
    settings = inventory_settings()
    financial = {}
    total_adjustment = ZERO
    processed = 0
    for key in keys:
        item = get_doc("Inventory Item", key["item_code"])
        if getattr(item, "valuation_method", "Moving Average") != "Weighted Average":
            continue
        conditions = [ledger.c.item_code == key["item_code"], ledger.c.warehouse == key["warehouse"],
                      ledger.c.batch == key["batch"], ledger.c.serial_number == key["serial_number"]]
        opening_stmt = select(
            func.coalesce(func.sum(ledger.c.actual_qty), 0).label("qty"),
            func.coalesce(func.sum(ledger.c.stock_value_difference), 0).label("value"),
        ).where(*conditions, ledger.c.posting_date < doc.period_start)
        opening = db.conn().execute(opening_stmt).mappings().one()
        period_rows = db.conn().execute(select(ledger).where(
            *conditions, ledger.c.posting_date >= doc.period_start, ledger.c.posting_date <= doc.period_end,
            ledger.c.voucher_type != "Inventory Valuation Closing",
        ).order_by(ledger.c.posting_date, ledger.c.name)).mappings().all()
        later = db.conn().execute(select(ledger.c.name).where(
            *conditions, ledger.c.posting_date > doc.period_end
        ).limit(1)).first()
        if later:
            throw(f"Cannot close {doc.period_start} to {doc.period_end}: later stock movements already exist for {item.name} in {key['warehouse']}.")
        try:
            result = periodic_weighted_average(opening["qty"], opening["value"], period_rows)
        except ValueError as exc:
            throw(f"Cannot close weighted average for {item.name} in {key['warehouse']}: {exc}")
        adjustment = result["valuation_adjustment"]
        if adjustment == 0:
            processed += 1
            continue
        current = get_stock_balance(key["item_code"], key["warehouse"], key["batch"], key["serial_number"])
        target = result["target_closing_value"]
        append_stock_ledger(
            posting_date=doc.posting_date, item_code=key["item_code"], warehouse=key["warehouse"],
            actual_qty=ZERO, qty_after=current["qty"], valuation_rate=result["weighted_average_rate"],
            value_difference=adjustment, value_after=target, voucher_type=doc.doctype,
            voucher_no=doc.name, batch=key["batch"], serial_number=key["serial_number"],
            remarks=f"Periodic weighted average close {doc.period_start} to {doc.period_end}",
        )
        asset = _asset_account(item, settings)
        if adjustment > 0:
            financial.setdefault(asset, [ZERO, ZERO])[0] += adjustment
            financial.setdefault(settings["cost_of_goods_sold_account"], [ZERO, ZERO])[1] += adjustment
        else:
            financial.setdefault(settings["cost_of_goods_sold_account"], [ZERO, ZERO])[0] += abs(adjustment)
            financial.setdefault(asset, [ZERO, ZERO])[1] += abs(adjustment)
        total_adjustment += adjustment
        processed += 1
    doc.processed_stock_keys = processed
    doc.total_value_adjustment = money(total_adjustment)
    from sqlalchemy import update
    db.conn().execute(update(get_table(doc.doctype)).where(get_table(doc.doctype).c.name == doc.name).values(
        processed_stock_keys=processed, total_value_adjustment=money(total_adjustment)
    ))
    if financial:
        from velora import get_list
        finance = get_list("Finance Settings", fields=["base_currency"], limit=1, ignore_permissions=True)
        if not finance:
            throw("Finance Settings must be configured before weighted average closing.")
        batch = _post_inventory_accounting(doc, doc.posting_date, finance[0]["base_currency"], 1,
            _net_posting_lines(financial, "Periodic weighted average inventory adjustment"), "WeightedAverageClose", doc.remarks)
        if batch:
            from sqlalchemy import update
            db.conn().execute(update(get_table(doc.doctype)).where(get_table(doc.doctype).c.name == doc.name).values(inventory_posting_batch=batch.name))
