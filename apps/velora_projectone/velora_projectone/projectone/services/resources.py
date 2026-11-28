"""Capacity and resource-allocation validation services."""
from decimal import Decimal, InvalidOperation


def _decimal(value, field):
    try: result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise ValueError(f"{field} must be numeric.")
    if not result.is_finite() or result < 0: raise ValueError(f"{field} must be finite and non-negative.")
    return result


def evaluate_resource_capacity(capacity_hours, allocations):
    """Return allocated/available hours and over-allocation per resource-period.

    Input allocations: [{resource_id, period, hours}]. Capacity keys are
    (resource_id, period) tuples. Multiple project allocations are aggregated.
    """
    if not isinstance(allocations, list): raise ValueError("allocations must be a list.")
    used = {}
    for row in allocations:
        rid, period = str(row.get("resource_id") or ""), str(row.get("period") or "")
        if not rid or not period: raise ValueError("Each allocation requires resource_id and period.")
        key = (rid, period)
        used[key] = used.get(key, Decimal("0")) + _decimal(row.get("hours"), "hours")
    result = []
    for key in sorted(set(capacity_hours) | set(used)):
        capacity = _decimal(capacity_hours.get(key, 0), "capacity_hours")
        allocated = used.get(key, Decimal("0"))
        result.append({"resource_id": key[0], "period": key[1], "capacity_hours": capacity,
                       "allocated_hours": allocated, "available_hours": capacity-allocated,
                       "utilisation_ratio": allocated/capacity if capacity else None,
                       "overallocated": allocated > capacity})
    return {"resources": result, "overallocated_count": sum(1 for r in result if r["overallocated"])}


def calculate_labour_cost(hours, cost_rate):
    hours, rate = _decimal(hours, "hours"), _decimal(cost_rate, "cost_rate")
    return {"hours": hours, "cost_rate": rate, "labour_cost": hours * rate}
