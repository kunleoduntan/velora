"""Inventory valuation algorithms used by the immutable stock ledger.

Moving Average is perpetual weighted average. FIFO consumes receipt layers in
chronological order. Weighted Average is periodic weighted average: movements
use a provisional moving rate and an approved period close adjusts ending stock
and COGS to the final period rate.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
QTY = Decimal("0.000001")
MONEY = Decimal("0.01")


def D(value):
    return Decimal(str(value if value is not None else 0))


def money(value):
    return D(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def fifo_consume(layers, quantity):
    """Consume quantity from oldest layers; return (cost, allocations, remaining).

    Each layer is {"qty": Decimal, "value": Decimal, "date": ...}. The input is
    copied so callers can safely use this as a pure calculation.
    """
    remaining = [{**layer, "qty": D(layer["qty"]), "value": money(layer["value"])} for layer in layers]
    requested = D(quantity).quantize(QTY, rounding=ROUND_HALF_UP)
    if requested < 0:
        raise ValueError("FIFO issue quantity must not be negative.")
    available = sum((layer["qty"] for layer in remaining), ZERO)
    if requested > available:
        raise ValueError(f"Insufficient FIFO layers: available {available}, requested {requested}.")
    allocations = []
    total = ZERO
    left = requested
    for layer in remaining:
        if left <= 0:
            break
        take = min(layer["qty"], left)
        if take <= 0:
            continue
        unit_rate = layer["value"] / layer["qty"] if layer["qty"] else ZERO
        layer_value = money(take * unit_rate)
        # Consume the final remainder of a layer exactly to avoid rounding drift.
        if take == layer["qty"]:
            layer_value = layer["value"]
        allocations.append({"qty": take, "value": layer_value, "rate": layer_value / take if take else ZERO})
        layer["qty"] -= take
        layer["value"] = money(layer["value"] - layer_value)
        total += layer_value
        left -= take
    remaining = [layer for layer in remaining if layer["qty"] > 0]
    return money(total), allocations, remaining


def apply_fifo_value_adjustment(layers, value_adjustment, layer_reference=None):
    """Apply a zero-quantity value adjustment to one layer or spread by quantity."""
    result = [{**layer, "qty": D(layer["qty"]), "value": money(layer["value"])} for layer in layers]
    adjustment = money(value_adjustment)
    if layer_reference:
        target = next((row for row in result if row.get("layer_id") == layer_reference), None)
        if target is None:
            raise ValueError(f"FIFO valuation layer {layer_reference} is not available.")
        target["value"] = money(target["value"] + adjustment)
        if target["value"] < 0:
            raise ValueError("FIFO valuation adjustment would make the referenced cost layer negative.")
        return result
    total_qty = sum((row["qty"] for row in result), ZERO)
    if not result or total_qty <= 0:
        if adjustment:
            raise ValueError("Cannot apply a FIFO value adjustment without remaining stock layers.")
        return result
    assigned = ZERO
    for index, layer in enumerate(result):
        if index == len(result) - 1:
            share = money(adjustment - assigned)
        else:
            share = money(adjustment * layer["qty"] / total_qty)
            assigned += share
        layer["value"] = money(layer["value"] + share)
        if layer["value"] < 0:
            raise ValueError("FIFO valuation adjustment would make a remaining cost layer negative.")
    return result


def periodic_weighted_average(opening_qty, opening_value, movements):
    """Return period weighted-average metrics from opening balances and movements.

    movements are dictionaries with actual_qty and stock_value_difference. Positive
    receipts and zero-quantity cost adjustments contribute to available value. Issues
    are costed provisionally during the period and reconciled at period close.
    """
    opening_qty, opening_value = D(opening_qty), money(opening_value)
    receipt_qty = ZERO
    available_value = opening_value
    issue_qty = ZERO
    provisional_issue_cost = ZERO
    net_qty = opening_qty
    current_value = opening_value
    for row in movements:
        qty = D(row.get("actual_qty"))
        value = money(row.get("stock_value_difference"))
        net_qty += qty
        current_value = money(current_value + value)
        if qty > 0:
            receipt_qty += qty
            available_value = money(available_value + value)
        elif qty < 0:
            issue_qty += abs(qty)
            provisional_issue_cost = money(provisional_issue_cost + abs(value))
        elif value:
            available_value = money(available_value + value)
    available_qty = opening_qty + receipt_qty
    if available_qty <= 0:
        if net_qty or current_value:
            raise ValueError("Periodic weighted average has value or closing quantity but no available quantity.")
        average_rate = ZERO
    else:
        average_rate = available_value / available_qty
    if net_qty < 0:
        raise ValueError("Periodic weighted average cannot close with negative stock quantity.")
    target_closing_value = money(net_qty * average_rate)
    adjustment = money(target_closing_value - current_value)
    return {
        "receipt_qty": receipt_qty,
        "available_qty": available_qty,
        "available_value": money(available_value),
        "issue_qty": issue_qty,
        "provisional_issue_cost": provisional_issue_cost,
        "weighted_average_rate": average_rate,
        "closing_qty": net_qty,
        "current_closing_value": money(current_value),
        "target_closing_value": target_closing_value,
        "valuation_adjustment": adjustment,
    }
