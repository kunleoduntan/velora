"""Date-aware enterprise resource capacity projections (read-only/advisory)."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import json


def _number(value, label, default=0):
    try:
        result = Decimal(str(default if value in (None, "") else value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")
    if not result.is_finite() or result < 0:
        raise ValueError(f"{label} must be finite and non-negative.")
    return result


def _date(value, label):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an ISO date.")


def _weekdays(value, default=(0, 1, 2, 3, 4)):
    if value in (None, ""):
        return set(default)
    try:
        vals = json.loads(value) if isinstance(value, str) and value.strip().startswith("[") else value
        if isinstance(vals, str):
            vals = [int(x.strip()) for x in vals.split(",") if x.strip()]
        result = {int(x) for x in vals}
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValueError("working_weekdays must contain weekday numbers 0-6.")
    if not result or any(x < 0 or x > 6 for x in result):
        raise ValueError("working_weekdays must contain one or more weekday numbers 0-6.")
    return result


def _holidays(value):
    if value in (None, ""):
        return set()
    try:
        vals = json.loads(value) if isinstance(value, str) and value.strip().startswith("[") else value
        if isinstance(vals, str):
            vals = [x.strip() for x in vals.replace(",", "\n").splitlines() if x.strip()]
        return {_date(x, "holiday date") for x in vals}
    except (TypeError, json.JSONDecodeError):
        raise ValueError("holiday_dates must be a JSON array or delimited ISO dates.")


def build_enterprise_capacity(profiles, tasks, allocations, calendars, exceptions, *, start_date, end_date):
    """Build a daily capacity heatmap from authorised, tenant-scoped read models.

    Task estimated effort is spread evenly across its working dates. Capacity is
    derived from Resource Profile and its calendar; an exception overrides that
    day's availability. Only explicitly approved/open project allocations are
    shown as governance context. No reservation or source-system write occurs.
    """
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    if end < start or (end - start).days > 365:
        raise ValueError("Date range must be ordered and no longer than 366 days.")
    calendar_by_id = {str(c.get("name")): c for c in calendars if c.get("active", True)}
    exception_rows = list(exceptions)

    profile_index = {}
    for p in profiles:
        if p.get("active", True) is False:
            continue
        rid = str(p.get("resource_id") or p.get("name") or "")
        if not rid:
            continue
        aliases = {rid, str(p.get("name") or ""), str(p.get("display_name") or ""), str(p.get("employee") or "")}
        profile_index[rid] = {"profile": p, "aliases": {x for x in aliases if x}}

    alias_candidates = defaultdict(set)
    for rid, info in profile_index.items():
        for alias in info["aliases"]:
            alias_candidates[alias].add(rid)
    # Ambiguous human-readable aliases are intentionally not resolved. Stable
    # Resource Profile IDs and document names remain deterministic identifiers.
    alias_to_resource = {alias: next(iter(ids)) for alias, ids in alias_candidates.items() if len(ids) == 1}
    exception_by_resource_day = {}
    for row in exception_rows:
        source_rid = str(row.get("resource") or row.get("resource_profile") or "")
        rid = alias_to_resource.get(source_rid)
        if not rid:
            continue
        day = _date(row.get("exception_date"), "exception_date")
        key = (rid, day)
        if key in exception_by_resource_day:
            raise ValueError(f"Duplicate availability exception for {rid} on {day.isoformat()}.")
        exception_by_resource_day[key] = _number(row.get("available_hours"), "available_hours")

    demand = defaultdict(Decimal)
    task_refs = defaultdict(set)
    excluded = []
    for task in tasks:
        if task.get("status") in ("Completed", "Cancelled"):
            continue
        assignee = str(task.get("resource_profile") or task.get("assignee") or task.get("resource") or "")
        match = alias_to_resource.get(assignee)
        if not match:
            continue
        if not task.get("planned_start") or not task.get("planned_finish"):
            excluded.append({"task": task.get("name"), "reason": "missing planned dates"})
            continue
        ts, te = _date(task["planned_start"], "task planned_start"), _date(task["planned_finish"], "task planned_finish")
        lo, hi = max(ts, start), min(te, end)
        if hi < lo:
            continue
        p = profile_index[match]["profile"]
        calendar_id = str(p.get("calendar_id") or "")
        if calendar_id and calendar_id not in calendar_by_id:
            raise ValueError(f"Resource {match} references a missing or inactive calendar {calendar_id}.")
        cal = calendar_by_id.get(calendar_id, {})
        weekdays = _weekdays(cal.get("working_weekdays") or p.get("working_weekdays"))
        holidays = _holidays(cal.get("holiday_dates"))
        workdays = []
        d = ts
        while d <= te:
            if d.weekday() in weekdays and d not in holidays:
                workdays.append(d)
            d += timedelta(days=1)
        if not workdays:
            excluded.append({"task": task.get("name"), "reason": "no working days in task interval"})
            continue
        hours = _number(task.get("estimated_hours"), "estimated_hours")
        per_day = hours / Decimal(len(workdays))
        for day in workdays:
            if start <= day <= end:
                demand[(match, day)] += per_day
                task_refs[(match, day)].add(str(task.get("name") or task.get("title") or "task"))

    daily, totals = [], defaultdict(lambda: {"capacity": Decimal(0), "demand": Decimal(0), "overloaded_days": 0, "days": 0})
    for rid, info in sorted(profile_index.items()):
        p = info["profile"]
        calendar_id = str(p.get("calendar_id") or "")
        if calendar_id and calendar_id not in calendar_by_id:
            raise ValueError(f"Resource {rid} references a missing or inactive calendar {calendar_id}.")
        cal = calendar_by_id.get(calendar_id, {})
        weekdays = _weekdays(cal.get("working_weekdays") or p.get("working_weekdays"))
        holidays = _holidays(cal.get("holiday_dates"))
        base_hours = _number(p.get("daily_capacity_hours"), "daily_capacity_hours", cal.get("hours_per_day", 8))
        active_from = _date(p["active_from"], "active_from") if p.get("active_from") else None
        active_to = _date(p["active_to"], "active_to") if p.get("active_to") else None
        d = start
        while d <= end:
            normally_available = d.weekday() in weekdays and d not in holidays and (not active_from or d >= active_from) and (not active_to or d <= active_to)
            cap = exception_by_resource_day.get((rid, d), base_hours if normally_available else Decimal(0))
            used = demand[(rid, d)]
            if cap or used:
                over = used > cap
                row = {"resource_id": rid, "display_name": p.get("display_name") or rid,
                       "date": d.isoformat(), "capacity_hours": cap, "demand_hours": used,
                       "available_after_demand": cap-used, "utilisation_ratio": (used/cap if cap else None),
                       "overallocated": over, "task_count": len(task_refs[(rid, d)]),
                       "task_refs": sorted(task_refs[(rid, d)])}
                daily.append(row)
                totals[rid]["capacity"] += cap; totals[rid]["demand"] += used
                totals[rid]["days"] += 1
                totals[rid]["overloaded_days"] += int(over)
            d += timedelta(days=1)
    summary = []
    for rid, values in sorted(totals.items()):
        summary.append({"resource_id": rid, "display_name": profile_index[rid]["profile"].get("display_name") or rid,
                        "capacity_hours": values["capacity"], "demand_hours": values["demand"],
                        "net_available_hours": values["capacity"]-values["demand"],
                        "overallocated_days": values["overloaded_days"], "active_days": values["days"],
                        "status": "Overallocated" if values["overloaded_days"] else "Within Capacity"})
    approved = [a for a in allocations if a.get("status") in ("Open", "In Progress") and
                (a.get("approved_by") or a.get("approval_reference"))]
    return {"period": {"start_date": start.isoformat(), "end_date": end.isoformat()},
            "resources": summary, "daily_capacity": daily,
            "approved_allocations": [{"project": a.get("project"), "resource": a.get("resource"),
                "start_date": a.get("start_date"), "end_date": a.get("end_date"),
                "planned_hours": _number(a.get("planned_hours"), "planned_hours"),
                "approval_reference": a.get("approval_reference")} for a in approved],
            "exceptions_count": len(exception_by_resource_day), "excluded_tasks": excluded,
            "metadata": {"read_only": True, "advisory": True, "resource_reservations_created": False,
                         "source_authority": "Velora ProjectOne resource profiles, calendars, task plans and approved project allocations"}}


def build_escalation_register(tasks, *, as_of=None, due_soon_days=3):
    """Calculate task escalation candidates; delivery requires a host notifier."""
    today = _date(as_of, "as_of") if as_of else date.today()
    if isinstance(due_soon_days, bool) or not isinstance(due_soon_days, int) or not 0 <= due_soon_days <= 30:
        raise ValueError("due_soon_days must be an integer from 0 to 30.")
    rows = []
    for task in tasks:
        if task.get("status") in ("Completed", "Cancelled") or not task.get("planned_finish"):
            continue
        due = _date(task["planned_finish"], "planned_finish")
        delta = (due-today).days
        if delta < 0:
            level, reason = "Overdue", "Task planned finish has passed"
        elif delta <= due_soon_days:
            level, reason = "Due Soon", "Task is within the configured escalation window"
        elif task.get("status") == "On Hold":
            level, reason = "Blocked", "Task is on hold"
        else:
            continue
        rows.append({"task": task.get("name"), "project": task.get("project"), "title": task.get("title"),
                     "assignee": task.get("assignee"), "planned_finish": due.isoformat(),
                     "days_to_due": delta, "status": task.get("status"), "priority": task.get("priority"),
                     "escalation": level, "reason": reason,
                     "notification_intent": {"event": "projectone.task.escalation", "task": task.get("name"),
                         "recipient": task.get("assignee"), "requires_host_notification_adapter": True}})
    rows.sort(key=lambda r: (0 if r["escalation"] == "Overdue" else 1 if r["escalation"] == "Blocked" else 2,
                             r["planned_finish"], str(r["task"])))
    return {"as_of": today.isoformat(), "items": rows, "count": len(rows),
            "delivery": "not_sent_host_notification_adapter_required", "read_only": True}
