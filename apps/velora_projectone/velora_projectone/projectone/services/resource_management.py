"""Enterprise resource pool, capacity, allocation and governed timesheets.

Pure domain layer. Tenant scope, record persistence, identity and workflow execution
must be enforced by the Velora host adapter. No payroll or GL posting is performed.
"""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

RESOURCE_TYPES = {"Employee", "Consultant", "Contractor", "Equipment", "Facility"}
TIMESHEET_STATES = {"Draft", "Submitted", "Approved", "Rejected", "Recalled"}


def _num(value, label, *, minimum=Decimal("0")):
    try:
        n = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")
    if not n.is_finite() or n < minimum:
        raise ValueError(f"{label} must be finite and at least {minimum}.")
    return n


def _date(value, label):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must use ISO YYYY-MM-DD format.")


def validate_resource_profile(resource):
    if not isinstance(resource, dict):
        raise ValueError("Resource profile must be an object.")
    required = ("resource_id", "resource_type", "display_name")
    missing = [k for k in required if not str(resource.get(k) or "").strip()]
    if missing:
        raise ValueError("Resource profile requires: " + ", ".join(missing))
    if resource["resource_type"] not in RESOURCE_TYPES:
        raise ValueError("Unsupported resource type.")
    capacity = _num(resource.get("daily_capacity_hours", 8), "daily_capacity_hours")
    if capacity > 24:
        raise ValueError("Daily capacity cannot exceed 24 hours.")
    active_from = resource.get("active_from")
    active_to = resource.get("active_to")
    if active_from:
        start = _date(active_from, "active_from")
        if active_to and _date(active_to, "active_to") < start:
            raise ValueError("active_to cannot precede active_from.")
    rate = _num(resource.get("cost_rate", 0), "cost_rate")
    weekdays = resource.get("working_weekdays", [0, 1, 2, 3, 4])
    if not isinstance(weekdays, (list, tuple)) or not weekdays or any(not isinstance(x, int) or x < 0 or x > 6 for x in weekdays):
        raise ValueError("working_weekdays must be a non-empty list of weekday numbers from 0 to 6.")
    return {"resource_id": str(resource["resource_id"]), "resource_type": resource["resource_type"],
            "display_name": str(resource["display_name"]).strip(), "daily_capacity_hours": capacity,
            "cost_rate": rate, "active": resource.get("active", True) is True,
            "calendar_id": resource.get("calendar_id"), "working_weekdays": tuple(weekdays)}


def match_resource_skills(requirements, resources):
    """Rank eligible resources by skill coverage, proficiency and availability flags."""
    output = []
    for req in requirements:
        needed = set(req.get("skills", []))
        candidates = []
        for resource in resources:
            if resource.get("active", True) is not True:
                continue
            skill_map = resource.get("skill_levels", {})
            have = set(resource.get("skills", [])) | set(skill_map)
            missing = sorted(needed - have)
            minimum = int(req.get("minimum_proficiency", 1))
            insufficient = sorted(s for s in needed if int(skill_map.get(s, 1)) < minimum)
            if not missing and not insufficient:
                levels = [int(skill_map.get(s, 1)) for s in needed]
                candidates.append({"resource_id": resource.get("resource_id"),
                    "match_score": round(sum(levels) / (5 * max(1, len(needed))), 4),
                    "skills_matched": sorted(needed), "proficiency": dict((s, skill_map.get(s, 1)) for s in sorted(needed)),
                    "availability_confirmed": resource.get("availability_confirmed", False) is True})
        output.append({"activity_id": req.get("activity_id"),
                       "candidates": sorted(candidates, key=lambda x: (-x["match_score"], str(x["resource_id"])))})
    return output


def _working_dates(start, end, weekdays=(0, 1, 2, 3, 4), holidays=()):
    weekdays = set(int(x) for x in weekdays)
    if not weekdays or any(x < 0 or x > 6 for x in weekdays):
        raise ValueError("working_weekdays must contain values from 0 to 6.")
    holiday_set = {str(x) for x in holidays}
    d = start
    while d <= end:
        if d.weekday() in weekdays and d.isoformat() not in holiday_set:
            yield d
        d += timedelta(days=1)


def build_resource_capacity(resources, *, start_date, end_date, allocations=(), exceptions=(), calendars=None, working_weekdays=(0,1,2,3,4), holidays=()):
    """Build date-level capacity and allocation by resource, honoring calendars/exceptions."""
    start, end = _date(start_date, "start_date"), _date(end_date, "end_date")
    if end < start:
        raise ValueError("end_date cannot precede start_date.")
    profiles = {str(r.get("resource_id")): validate_resource_profile(r) for r in resources}
    if len(profiles) != len(resources):
        raise ValueError("Resource IDs must be unique in the supplied scope.")
    calendars = calendars or {}
    exception_map = {}
    for ex in exceptions:
        rid = str(ex.get("resource_id") or "")
        day = _date(ex.get("date"), "exception date").isoformat()
        if rid not in profiles:
            raise ValueError(f"Unknown resource in availability exception: {rid}")
        exception_hours = _num(ex.get("available_hours", 0), "exception available_hours")
        if exception_hours > 24:
            raise ValueError("Exception available_hours cannot exceed 24.")
        exception_map[(rid, day)] = exception_hours
    used = {}
    for allocation in allocations:
        rid = str(allocation.get("resource_id") or "")
        if rid not in profiles:
            raise ValueError(f"Unknown allocated resource: {rid}")
        astart = _date(allocation.get("start_date"), "allocation start_date")
        aend = _date(allocation.get("end_date"), "allocation end_date")
        if aend < astart:
            raise ValueError("Allocation end_date cannot precede start_date.")
        hours = _num(allocation.get("hours_per_day", 0), "hours_per_day")
        if hours > 24:
            raise ValueError("Allocation hours_per_day cannot exceed 24.")
        if allocation.get("status", "Active") in {"Cancelled", "Completed", "On Hold"}:
            continue
        for day in _working_dates(max(start, astart), min(end, aend), working_weekdays, holidays):
            key = (rid, day.isoformat())
            used[key] = used.get(key, Decimal("0")) + hours
    rows = []
    for rid, profile in sorted(profiles.items()):
        active_from = _date(profile.get("active_from"), "active_from") if profile.get("active_from") else start
        active_to = _date(profile.get("active_to"), "active_to") if profile.get("active_to") else end
        calendar = calendars.get(profile.get("calendar_id"), {}) if profile.get("calendar_id") else {}
        resource_weekdays = tuple(calendar.get("working_weekdays", profile["working_weekdays"]))
        resource_holidays = tuple(calendar.get("holidays", holidays))
        for day in _working_dates(start, end, resource_weekdays, resource_holidays):
            if day < active_from or day > active_to or not profile["active"]:
                continue
            key = (rid, day.isoformat())
            capacity = exception_map.get(key, profile["daily_capacity_hours"])
            allocated = used.get(key, Decimal("0"))
            rows.append({"resource_id": rid, "date": day.isoformat(), "capacity_hours": capacity,
                         "allocated_hours": allocated, "available_hours": capacity-allocated,
                         "utilisation_ratio": allocated/capacity if capacity else None,
                         "overallocated": allocated > capacity})
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "days": rows,
            "overallocated_count": sum(1 for r in rows if r["overallocated"]),
            "total_capacity_hours": sum((r["capacity_hours"] for r in rows), Decimal("0")),
            "total_allocated_hours": sum((r["allocated_hours"] for r in rows), Decimal("0"))}


def validate_allocation(allocation):
    required = ("allocation_id", "project", "resource_id", "start_date", "end_date")
    missing = [k for k in required if not str(allocation.get(k) or "").strip()]
    if missing:
        raise ValueError("Allocation requires: " + ", ".join(missing))
    start, end = _date(allocation["start_date"], "start_date"), _date(allocation["end_date"], "end_date")
    if end < start:
        raise ValueError("Allocation end_date cannot precede start_date.")
    hours = _num(allocation.get("hours_per_day", 0), "hours_per_day")
    if hours > 24:
        raise ValueError("hours_per_day cannot exceed 24.")
    if allocation.get("allocation_percent") is not None:
        pct = _num(allocation["allocation_percent"], "allocation_percent")
        if pct > 100:
            raise ValueError("allocation_percent cannot exceed 100.")
    return {"valid": True, "allocation_id": allocation["allocation_id"], "project": allocation["project"],
            "resource_id": allocation["resource_id"], "start_date": start.isoformat(), "end_date": end.isoformat(),
            "hours_per_day": hours}


def evaluate_utilisation(capacity_rows, *, warning_threshold=Decimal("0.85")):
    threshold = _num(warning_threshold, "warning_threshold")
    if threshold > 1:
        raise ValueError("warning_threshold must be between 0 and 1.")
    by_resource = {}
    for row in capacity_rows:
        rid = str(row.get("resource_id") or "")
        if not rid:
            raise ValueError("Each capacity row requires resource_id.")
        bucket = by_resource.setdefault(rid, {"capacity_hours": Decimal("0"), "allocated_hours": Decimal("0"), "overallocated_days": 0})
        cap, used = _num(row.get("capacity_hours"), "capacity_hours"), _num(row.get("allocated_hours"), "allocated_hours")
        bucket["capacity_hours"] += cap
        bucket["allocated_hours"] += used
        bucket["overallocated_days"] += int(used > cap)
    result = []
    for rid, values in sorted(by_resource.items()):
        cap, used = values["capacity_hours"], values["allocated_hours"]
        ratio = used / cap if cap else None
        result.append({"resource_id": rid, **values, "utilisation_ratio": ratio,
                       "overallocated": values["overallocated_days"] > 0,
                       "high_utilisation": ratio is not None and ratio >= threshold})
    return {"resources": result, "resource_count": len(result),
            "overallocated_resources": sum(x["overallocated"] for x in result),
            "high_utilisation_resources": sum(x["high_utilisation"] for x in result)}


def level_resource_assignments(assignments, capacity_by_resource_date):
    """Deterministic priority-first day allocation; returns shortages, never hides them."""
    remaining = {k: _num(v, "capacity") for k, v in capacity_by_resource_date.items()}
    output = []
    ordered = sorted(assignments, key=lambda x: (int(x.get("priority", 999)), str(x.get("start_date", "")), str(x.get("allocation_id", ""))))
    for item in ordered:
        checked = validate_allocation(item)
        rid = str(item["resource_id"])
        start, end = _date(item["start_date"], "start_date"), _date(item["end_date"], "end_date")
        requested = _num(item.get("hours_per_day", 0), "hours_per_day")
        per_day = []
        for day in _working_dates(start, end, tuple(item.get("working_weekdays", [0,1,2,3,4])), item.get("holidays", [])):
            key = (rid, day.isoformat())
            available = remaining.get(key, Decimal("0"))
            assigned = min(requested, available)
            remaining[key] = available-assigned
            per_day.append({"date": day.isoformat(), "requested_hours": requested,
                            "assigned_hours": assigned, "unassigned_hours": requested-assigned})
        shortage = sum((x["unassigned_hours"] for x in per_day), Decimal("0"))
        output.append({"allocation_id": checked["allocation_id"], "resource_id": rid,
                       "project": checked["project"], "days": per_day,
                       "unassigned_hours": shortage, "fully_levelled": shortage == 0})
    return {"allocations": output, "total_unassigned_hours": sum((x["unassigned_hours"] for x in output), Decimal("0")),
            "heuristic": "priority, planned start, allocation ID; no schedule dates or source allocations mutated"}


def validate_timesheet(timesheet, *, existing_approved_hours=()):
    required = ("employee", "project", "work_date", "hours", "submitted_by")
    missing = [k for k in required if not str(timesheet.get(k) if timesheet.get(k) is not None else "").strip()]
    if not str(timesheet.get("timesheet_id") or timesheet.get("name") or "").strip():
        missing.insert(0, "timesheet_id/name")
    if missing:
        raise ValueError("Timesheet requires: " + ", ".join(missing))
    day = _date(timesheet["work_date"], "work_date")
    hours = _num(timesheet["hours"], "hours", minimum=Decimal("0.01"))
    if hours > 24:
        raise ValueError("Daily timesheet hours cannot exceed 24.")
    state = timesheet.get("status", timesheet.get("approval_status", "Draft"))
    if state == "Pending Approval":
        state = "Submitted"
    if state not in TIMESHEET_STATES:
        raise ValueError("Unsupported timesheet status.")
    existing = sum((_num(x, "existing approved hours") for x in existing_approved_hours), Decimal("0"))
    if state == "Approved" and existing + hours > 24:
        raise ValueError("Approved hours for an employee and date cannot exceed 24.")
    if state == "Approved":
        if not timesheet.get("approved_by") or not timesheet.get("approval_reference"):
            raise ValueError("Approved timesheet requires approver and approval reference.")
        if str(timesheet["approved_by"]) == str(timesheet["submitted_by"]):
            raise ValueError("Timesheet submitter cannot approve their own entry.")
    return {"valid": True, "timesheet_id": timesheet.get("timesheet_id") or timesheet.get("name"), "work_date": day.isoformat(),
            "hours": hours, "status": state, "payroll_handoff_permitted": state == "Approved",
            "posting_authority": "Payroll/Accounting", "ledger_write_permitted": False}


def transition_timesheet(timesheet, target_status, *, actor_id, approval_reference=None):
    """Return a validated state change; caller persists it with host audit/workflow."""
    from copy import deepcopy
    current = timesheet.get("status", timesheet.get("approval_status", "Draft"))
    if current == "Pending Approval":
        current = "Submitted"
    allowed = {"Draft": {"Submitted"}, "Submitted": {"Approved", "Rejected", "Recalled"},
               "Rejected": {"Draft"}, "Recalled": {"Draft"}, "Approved": set()}
    if target_status not in allowed.get(current, set()):
        raise ValueError(f"Invalid timesheet transition: {current} -> {target_status}")
    changed = deepcopy(timesheet)
    if target_status == "Approved":
        changed["approved_by"] = actor_id
        changed["approval_reference"] = approval_reference
        validate_timesheet({**changed, "status": "Approved"})
    elif target_status == "Submitted":
        if not changed.get("submitted_by"):
            changed["submitted_by"] = actor_id
        changed["submitted_on"] = changed.get("submitted_on")
    changed["status"] = target_status
    if "approval_status" in changed:
        changed["approval_status"] = "Pending Approval" if target_status == "Submitted" else target_status
    if target_status in {"Rejected", "Recalled"}:
        changed["approved_by"] = None
        changed["approval_reference"] = None
    return changed


def expand_approved_timesheets(timesheets):
    """Expand approved weekly headers into uniquely identified daily hand-off rows."""
    expanded = []
    for sheet in timesheets:
        status = sheet.get("status", sheet.get("approval_status", "Draft"))
        if status == "Pending Approval":
            status = "Submitted"
        if status != "Approved":
            continue
        if not sheet.get("approved_by") or not sheet.get("approval_reference") or not sheet.get("submitted_by"):
            raise ValueError("Approved weekly timesheet requires submitter, approver and approval reference.")
        lines = sheet.get("entries") or []
        if not lines:
            raise ValueError(f"Approved timesheet {sheet.get('name') or sheet.get('timesheet_id')} has no daily entries.")
        for index, line in enumerate(lines, start=1):
            expanded.append({"timesheet_id": f"{sheet.get('name') or sheet.get('timesheet_id')}:{line.get('name') or index}",
                "employee": sheet["employee"], "project": line.get("project") or sheet.get("project"),
                "work_date": line.get("work_date"), "hours": line.get("hours"), "status": "Approved",
                "submitted_by": sheet["submitted_by"], "approved_by": sheet["approved_by"],
                "approval_reference": sheet["approval_reference"], "billable": line.get("billable", True),
                "activity": line.get("activity"), "task": line.get("task")})
    return expanded


def approved_hours_handoff(entries, *, company_id, handoff_batch_id):
    """Create a payroll-facing payload from approved, uniquely identified entries only."""
    if not company_id or not handoff_batch_id:
        raise ValueError("company_id and handoff_batch_id are required.")
    seen = set(); rows = []; daily_totals = {}
    for entry in entries:
        if entry.get("status") != "Approved":
            continue
        checked = validate_timesheet(entry)
        sid = checked["timesheet_id"]
        if sid in seen:
            raise ValueError(f"Duplicate timesheet in hand-off: {sid}")
        seen.add(sid)
        day_key = (str(entry["employee"]), checked["work_date"])
        daily_totals[day_key] = daily_totals.get(day_key, Decimal("0")) + checked["hours"]
        if daily_totals[day_key] > 24:
            raise ValueError(f"Approved project hours exceed 24 for employee {day_key[0]} on {day_key[1]}.")
        rows.append({"timesheet_id": sid, "employee": entry["employee"], "project": entry["project"],
                     "work_date": checked["work_date"], "approved_hours": checked["hours"],
                     "approval_reference": entry["approval_reference"]})
    return {"company_id": company_id, "handoff_batch_id": handoff_batch_id, "entries": rows,
            "entry_count": len(rows), "destination": "HRMS/Payroll integration inbox",
            "requires_destination_acknowledgement": True, "payroll_calculation_performed": False,
            "gl_posting_performed": False, "ledger_write_permitted": False}
