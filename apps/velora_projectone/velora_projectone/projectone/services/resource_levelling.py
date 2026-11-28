"""Explainable, non-persistent resource levelling and workload forecasts."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def _decimal(value, field):
    try:
        result = Decimal(str(0 if value in (None, "") else value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric.")
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be finite and non-negative.")
    return result


def _iso(value, field):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an ISO date.")


def build_workload_forecast(daily_capacity, *, bucket="week"):
    """Aggregate authorised daily resource facts into week or month buckets."""
    if bucket not in ("week", "month"):
        raise ValueError("bucket must be 'week' or 'month'.")
    grouped = defaultdict(lambda: {"capacity_hours": Decimal(0), "demand_hours": Decimal(0),
                                   "overallocated_days": 0, "days": 0, "resources": set()})
    for row in daily_capacity:
        day = _iso(row.get("date"), "date")
        if bucket == "week":
            iso = day.isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            key = day.strftime("%Y-%m")
        item = grouped[key]
        item["capacity_hours"] += _decimal(row.get("capacity_hours"), "capacity_hours")
        item["demand_hours"] += _decimal(row.get("demand_hours"), "demand_hours")
        item["overallocated_days"] += int(bool(row.get("overallocated")))
        item["days"] += 1
        item["resources"].add(str(row.get("resource_id") or ""))
    result = []
    for key, item in sorted(grouped.items()):
        capacity, demand = item["capacity_hours"], item["demand_hours"]
        result.append({"period": key, "capacity_hours": capacity, "demand_hours": demand,
                       "net_available_hours": capacity-demand,
                       "utilisation_ratio": demand/capacity if capacity else None,
                       "overallocated_days": item["overallocated_days"],
                       "resource_count": len(item["resources"] - {""}), "resource_days": item["days"]})
    return {"bucket": bucket, "periods": result, "read_only": True,
            "method": "sum of authorised daily capacity and scheduled demand; no extrapolation beyond supplied dates"}


def preview_resource_levelling(tasks, profiles, daily_capacity, *, priority_order=None):
    """Greedy, deterministic daily levelling within each task's existing date window.

    This is a recommendation only. It never changes task dates, assignments,
    approved allocations, HRMS availability or resource reservations.
    """
    priority_order = priority_order or {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}
    profile_aliases = defaultdict(set)
    for profile in profiles:
        if profile.get("active", True) is False:
            continue
        rid = str(profile.get("resource_id") or profile.get("name") or "")
        if rid:
            for alias in (rid, profile.get("name"), profile.get("display_name"), profile.get("employee")):
                if alias:
                    profile_aliases[str(alias)].add(rid)
    aliases = {k: next(iter(v)) for k, v in profile_aliases.items() if len(v) == 1}
    remaining = {}
    for row in daily_capacity:
        rid, day = str(row.get("resource_id") or ""), _iso(row.get("date"), "date")
        remaining[(rid, day)] = _decimal(row.get("capacity_hours"), "capacity_hours")
    ordered = sorted(tasks, key=lambda t: (priority_order.get(str(t.get("priority") or "Normal"), 99),
                                            str(t.get("planned_start") or "9999-12-31"),
                                            str(t.get("name") or "")))
    results, total_unassigned = [], Decimal(0)
    for task in ordered:
        if task.get("status") in ("Completed", "Cancelled"):
            continue
        ref = str(task.get("resource_profile") or task.get("resource_id") or task.get("assignee") or "")
        rid = aliases.get(ref)
        if not rid:
            results.append({"task": task.get("name"), "resource_id": None, "requested_hours": _decimal(task.get("estimated_hours"), "estimated_hours"),
                            "assigned_hours": Decimal(0), "unassigned_hours": _decimal(task.get("estimated_hours"), "estimated_hours"),
                            "reason": "No unique active Resource Profile match"})
            total_unassigned += _decimal(task.get("estimated_hours"), "estimated_hours")
            continue
        if not task.get("planned_start") or not task.get("planned_finish"):
            hours = _decimal(task.get("estimated_hours"), "estimated_hours")
            results.append({"task": task.get("name"), "resource_id": rid, "requested_hours": hours,
                            "assigned_hours": Decimal(0), "unassigned_hours": hours, "reason": "Missing planned date window"})
            total_unassigned += hours
            continue
        start, finish = _iso(task["planned_start"], "planned_start"), _iso(task["planned_finish"], "planned_finish")
        if finish < start or (finish-start).days > 366:
            raise ValueError(f"Task {task.get('name')} has an invalid or excessive date window.")
        hours = _decimal(task.get("estimated_hours"), "estimated_hours")
        days = [start + timedelta(days=i) for i in range((finish-start).days+1)
                if (rid, start+timedelta(days=i)) in remaining]
        left, plan = hours, []
        for day in days:
            available = remaining[(rid, day)]
            assigned = min(left, available)
            if assigned:
                plan.append({"date": day.isoformat(), "hours": assigned})
                remaining[(rid, day)] = available-assigned
                left -= assigned
            if left <= 0:
                break
        assigned_total = hours-left
        total_unassigned += left
        results.append({"task": task.get("name"), "resource_id": rid, "priority": task.get("priority"),
                        "requested_hours": hours, "assigned_hours": assigned_total,
                        "unassigned_hours": left, "daily_plan": plan,
                        "reason": "Capacity-constrained preview; task dates and assignment remain unchanged"})
    return {"allocations": results, "unassigned_hours": total_unassigned,
            "method": "priority then planned start then task ID; greedily consumes available daily capacity",
            "optimality": "heuristic_not_optimal_rcpsp", "read_only": True,
            "schedule_dates_changed": False, "resource_reservations_created": False}
