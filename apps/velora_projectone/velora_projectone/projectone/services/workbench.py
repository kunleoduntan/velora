"""Deterministic project-manager workbench projections (read-only)."""
from __future__ import annotations
from datetime import date

STATUSES = ("Draft", "Open", "In Progress", "On Hold", "Completed", "Cancelled")


def build_task_board(tasks: list[dict], *, as_of: str | None = None,
                     assignee: str | None = None, priority: str | None = None) -> dict:
    """Build status lanes and action centre from authorised native task rows."""
    today = date.fromisoformat(as_of) if as_of else date.today()
    rows = []
    for source in tasks:
        task = dict(source)
        if assignee and task.get("assignee") != assignee:
            continue
        if priority and task.get("priority") != priority:
            continue
        due = date.fromisoformat(str(task["planned_finish"])[:10]) if task.get("planned_finish") else None
        task["days_overdue"] = max(0, (today - due).days) if due and due < today and task.get("status") != "Completed" else 0
        task["is_overdue"] = bool(task["days_overdue"])
        task["is_blocked"] = task.get("status") == "On Hold" or bool(task.get("blocked_by"))
        rows.append(task)
    lanes = {status: [] for status in STATUSES}
    for task in rows:
        lanes.setdefault(task.get("status") or "Unclassified", []).append(task)
    for lane in lanes.values():
        lane.sort(key=lambda t: (t.get("planned_finish") or "9999-12-31", t.get("priority") != "Critical", t.get("title") or ""))
    overdue = sorted((t for t in rows if t["is_overdue"]), key=lambda t: (-t["days_overdue"], t.get("planned_finish") or ""))
    due_soon = sorted((t for t in rows if not t["is_overdue"] and t.get("planned_finish") and t.get("status") not in ("Completed", "Cancelled") and 0 <= (date.fromisoformat(str(t["planned_finish"])[:10]) - today).days <= 7), key=lambda t: t.get("planned_finish"))
    blocked = [t for t in rows if t["is_blocked"]]
    unassigned = [t for t in rows if not t.get("assignee") and t.get("status") not in ("Completed", "Cancelled")]
    return {"as_of": today.isoformat(), "total": len(rows), "lanes": lanes,
            "action_centre": {"overdue": overdue, "due_within_7_days": due_soon,
                              "blocked": blocked, "unassigned": unassigned},
            "counts": {"overdue": len(overdue), "due_within_7_days": len(due_soon),
                       "blocked": len(blocked), "unassigned": len(unassigned)}}


def resource_capacity_warnings(tasks: list[dict], allocations: list[dict]) -> list[dict]:
    """Compare task demand against active, explicitly approved project allocations.

    Task effort is compared with planned allocation hours over overlapping date
    windows. This is a conservative project-level warning, not an enterprise
    timesheet/capacity ledger; it never reserves capacity or mutates HRMS data.
    """
    from datetime import date
    active = [a for a in allocations if a.get("status") in ("Open", "In Progress")
              and (a.get("approved_by") or a.get("approval_reference"))
              and a.get("resource") and a.get("planned_hours") is not None]
    warnings = []
    for allocation in active:
        resource = allocation["resource"]
        start = date.fromisoformat(str(allocation["start_date"])[:10]) if allocation.get("start_date") else None
        end = date.fromisoformat(str(allocation["end_date"])[:10]) if allocation.get("end_date") else None
        relevant = []
        for task in tasks:
            if task.get("assignee") != resource or task.get("status") in ("Completed", "Cancelled"):
                continue
            ts = date.fromisoformat(str(task["planned_start"])[:10]) if task.get("planned_start") else None
            te = date.fromisoformat(str(task["planned_finish"])[:10]) if task.get("planned_finish") else None
            if start and te and te < start: continue
            if end and ts and ts > end: continue
            relevant.append(task)
        demand = sum(float(t.get("estimated_hours") or 0) for t in relevant)
        capacity = float(allocation.get("planned_hours") or 0)
        if demand > capacity:
            warnings.append({"resource": resource, "allocation": allocation.get("name"),
                             "start_date": allocation.get("start_date"), "end_date": allocation.get("end_date"),
                             "demand_hours": round(demand, 2), "allocated_hours": round(capacity, 2),
                             "excess_hours": round(demand-capacity, 2),
                             "severity": "High" if demand > capacity * 1.25 else "Medium",
                             "task_count": len(relevant)})
    return warnings
