"""Enterprise CPM, free-float, baseline variance and Gantt projection services.

Durations/lags are integer working-day units. Calendar date conversion is explicit
and delegated to the existing project calendar service.
"""
from __future__ import annotations
from collections import defaultdict, deque
from datetime import date
from .calendar import add_working_days, working_days_between
from .scheduling import VALID_TYPES


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer greater than or equal to {minimum}.")
    return value


def _date(value, label):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must use ISO YYYY-MM-DD format.")


def validate_dependencies(activities):
    """Validate unique task IDs, references, relationship types and acyclic graph."""
    if not isinstance(activities, list):
        raise ValueError("activities must be a list.")
    rows = {}
    for raw in activities:
        if not isinstance(raw, dict):
            raise ValueError("Each activity must be an object.")
        task_id = str(raw.get("id") or "").strip()
        if not task_id or task_id in rows:
            raise ValueError("Activity IDs must be present and unique.")
        duration = _integer(raw.get("duration"), f"{task_id} duration")
        rows[task_id] = {"id": task_id, "duration": duration, "raw": raw}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    indegree = {task_id: 0 for task_id in rows}
    edges = []
    for task_id, row in rows.items():
        dependencies = row["raw"].get("dependencies")
        if dependencies is None:
            dependencies = [{"predecessor": p, "type": "FS", "lag": 0}
                            for p in row["raw"].get("predecessors", [])]
        if not isinstance(dependencies, list):
            raise ValueError(f"{task_id}: dependencies must be a list.")
        for dep in dependencies:
            if isinstance(dep, str):
                dep = {"predecessor": dep}
            if not isinstance(dep, dict):
                raise ValueError(f"{task_id}: dependency must be an object.")
            pred = str(dep.get("predecessor") or "")
            rel = str(dep.get("type", "FS")).upper()
            lag = dep.get("lag", 0)
            if pred not in rows or pred == task_id:
                raise ValueError(f"{task_id}: invalid predecessor {pred}.")
            if rel not in VALID_TYPES:
                raise ValueError(f"Unsupported relationship type: {rel}")
            if isinstance(lag, bool) or not isinstance(lag, int):
                raise ValueError("Dependency lag must be an integer working-day value.")
            incoming[task_id].append((pred, rel, lag))
            outgoing[pred].append((task_id, rel, lag))
            edges.append((pred, task_id, rel, lag))
            indegree[task_id] += 1
    queue = deque(sorted(k for k, n in indegree.items() if n == 0))
    order = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for successor, _, _ in outgoing[current]:
            indegree[successor] -= 1
            if indegree[successor] == 0:
                queue.append(successor)
    if len(order) != len(rows):
        raise ValueError("Dependency cycle detected; schedule cannot be calculated.")
    return rows, incoming, outgoing, order, edges


def calculate_cpm(activities):
    """Return ES/EF/LS/LF, total/free float, critical path and milestones."""
    rows, incoming, outgoing, order, edges = validate_dependencies(activities)
    es, ef = {}, {}
    for task_id in order:
        duration = rows[task_id]["duration"]
        requested_start = rows[task_id]["raw"].get("planned_start_offset", 0)
        requested_start = _integer(requested_start, f"{task_id} planned_start_offset")
        candidates = [requested_start]
        for pred, rel, lag in incoming[task_id]:
            if rel == "FS": candidates.append(ef[pred] + lag)
            elif rel == "SS": candidates.append(es[pred] + lag)
            elif rel == "FF": candidates.append(ef[pred] + lag - duration)
            else: candidates.append(es[pred] + lag - duration)
        es[task_id] = max(candidates)
        ef[task_id] = es[task_id] + duration
    project_duration = max(ef.values(), default=0)
    ls, lf = {}, {}
    for task_id in reversed(order):
        duration = rows[task_id]["duration"]
        limits = [project_duration - duration]
        for succ, rel, lag in outgoing[task_id]:
            succ_duration = rows[succ]["duration"]
            if rel == "FS": limits.append(ls[succ] - lag - duration)
            elif rel == "SS": limits.append(ls[succ] - lag)
            elif rel == "FF": limits.append(ls[succ] + succ_duration - lag - duration)
            else: limits.append(ls[succ] + succ_duration - lag - duration)
        ls[task_id] = min(limits)
        lf[task_id] = ls[task_id] + duration
    output = []
    for task_id in order:
        duration = rows[task_id]["duration"]
        successor_limits = []
        for succ, rel, lag in outgoing[task_id]:
            if rel == "FS": successor_limits.append(es[succ] - ef[task_id] - lag)
            elif rel == "SS": successor_limits.append(es[succ] - es[task_id] - lag)
            elif rel == "FF": successor_limits.append(ef[succ] - ef[task_id] - lag)
            else: successor_limits.append(ef[succ] - es[task_id] - lag)
        free_float = min(successor_limits) if successor_limits else project_duration - ef[task_id]
        total_float = ls[task_id] - es[task_id]
        raw = rows[task_id]["raw"]
        output.append({
            "id": task_id, "name": raw.get("name") or raw.get("title") or task_id,
            "wbs": raw.get("wbs"), "duration": duration,
            "early_start": es[task_id], "early_finish": ef[task_id],
            "late_start": ls[task_id], "late_finish": lf[task_id],
            "total_float": total_float, "free_float": free_float,
            "critical": total_float == 0, "milestone": duration == 0,
            "predecessors": [{"id": p, "type": rel, "lag": lag} for p, rel, lag in incoming[task_id]],
            "assignee": raw.get("assignee"), "status": raw.get("status", "Not Started"),
            "progress_percent": raw.get("progress_percent", 0),
        })
    return {"duration": project_duration, "activities": output,
            "critical_activities": [r["id"] for r in output if r["critical"]],
            "critical_paths": "critical activities are identified; where multiple zero-float paths exist they are all represented",
            "time_unit": "working-day units"}


def calculate_gantt(activities, project_start, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
    """Produce date-positioned Gantt rows and CPM data using a working calendar."""
    start = _date(project_start, "project_start")
    cpm = calculate_cpm(activities)
    rows = []
    for task in cpm["activities"]:
        es = add_working_days(start.isoformat(), task["early_start"], working_weekdays, holidays)
        # Finish is inclusive; zero-duration milestones occur on their start date.
        ef = es if task["duration"] == 0 else add_working_days(es, task["duration"] - 1, working_weekdays, holidays)
        ls = add_working_days(start.isoformat(), task["late_start"], working_weekdays, holidays)
        lf = ls if task["duration"] == 0 else add_working_days(ls, task["duration"] - 1, working_weekdays, holidays)
        rows.append({**task, "early_start_date": es, "early_finish_date": ef,
                     "late_start_date": ls, "late_finish_date": lf,
                     "bar_offset_days": task["early_start"],
                     "bar_duration_days": task["duration"]})
    finish = max((_date(r["early_finish_date"], "finish") for r in rows), default=start)
    return {**cpm, "project_start": start.isoformat(), "project_finish": finish.isoformat(),
            "gantt_rows": rows, "working_weekdays": list(working_weekdays),
            "holidays": sorted(set(holidays)),
            "duration_calendar_days": (finish - start).days + 1}


def compare_schedule_to_baseline(current, baseline):
    """Compare task date snapshots; missing tasks are explicitly reported."""
    if not isinstance(current, list) or not isinstance(baseline, list):
        raise ValueError("current and baseline must be lists of task snapshots.")
    def index(rows, label):
        out = {}
        for row in rows:
            key = str(row.get("id") or "")
            if not key or key in out: raise ValueError(f"{label} task IDs must be present and unique.")
            out[key] = row
        return out
    cur, base = index(current, "Current"), index(baseline, "Baseline")
    results = []
    for task_id in sorted(set(cur) | set(base)):
        c, b = cur.get(task_id), base.get(task_id)
        if c is None:
            results.append({"id": task_id, "change": "Removed", "start_variance_days": None, "finish_variance_days": None})
            continue
        if b is None:
            results.append({"id": task_id, "change": "Added", "start_variance_days": None, "finish_variance_days": None})
            continue
        cs, bs = _date(c.get("start_date"), "current start"), _date(b.get("start_date"), "baseline start")
        cf, bf = _date(c.get("finish_date"), "current finish"), _date(b.get("finish_date"), "baseline finish")
        results.append({"id": task_id, "change": "Changed" if (cs, cf) != (bs, bf) else "Unchanged",
                        "start_variance_days": (cs-bs).days, "finish_variance_days": (cf-bf).days,
                        "baseline_start": bs.isoformat(), "current_start": cs.isoformat(),
                        "baseline_finish": bf.isoformat(), "current_finish": cf.isoformat()})
    return {"tasks": results, "changed_count": sum(x["change"] != "Unchanged" for x in results),
            "delayed_count": sum((x.get("finish_variance_days") or 0) > 0 for x in results),
            "baseline_is_read_only": True}


def preview_schedule_change(activities, project_start, task_id, proposed_start_offset,
                           working_weekdays=(0, 1, 2, 3, 4), holidays=(), baseline=None):
    """Preview a task start constraint and its downstream CPM impact.

    This is a pure calculation: it does not persist task dates, alter a baseline,
    reserve resources or execute a workflow transition.
    """
    if not isinstance(activities, list) or not activities:
        raise ValueError("activities must be a non-empty list.")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id is required.")
    offset = _integer(proposed_start_offset, "proposed_start_offset")
    before = calculate_gantt(activities, project_start, working_weekdays, holidays)
    known = {row["id"] for row in before["activities"]}
    if task_id not in known:
        raise ValueError("task_id does not exist in the supplied schedule.")
    changed = []
    found = False
    for row in activities:
        item = dict(row)
        if str(item.get("id")) == task_id:
            item["planned_start_offset"] = offset
            found = True
        changed.append(item)
    after = calculate_gantt(changed, project_start, working_weekdays, holidays)
    old_rows = {row["id"]: row for row in before["gantt_rows"]}
    new_rows = {row["id"]: row for row in after["gantt_rows"]}
    impacts = []
    for key in sorted(old_rows):
        old, new = old_rows[key], new_rows[key]
        start_delta = ( _date(new["early_start_date"], "new start") -
                        _date(old["early_start_date"], "old start")).days
        finish_delta = ( _date(new["early_finish_date"], "new finish") -
                         _date(old["early_finish_date"], "old finish")).days
        if start_delta or finish_delta:
            impacts.append({"task_id": key, "start_variance_calendar_days": start_delta,
                            "finish_variance_calendar_days": finish_delta,
                            "previous_start": old["early_start_date"],
                            "proposed_start": new["early_start_date"],
                            "previous_finish": old["early_finish_date"],
                            "proposed_finish": new["early_finish_date"]})
    result = {"project_start": after["project_start"], "task_id": task_id,
              "proposed_start_offset": offset,
              "previous_project_finish": before["project_finish"],
              "proposed_project_finish": after["project_finish"],
              "project_finish_variance_calendar_days":
                  (_date(after["project_finish"], "finish") - _date(before["project_finish"], "finish")).days,
              "changed_task_count": len(impacts), "impacts": impacts,
              "schedule": after, "preview_only": True, "persisted": False,
              "baseline_modified": False, "resource_reservations_created": False,
              "approval_required_before_commit": True}
    if baseline is not None:
        result["baseline_comparison"] = compare_schedule_to_baseline(
            [{"id": r["id"], "start_date": r["early_start_date"], "finish_date": r["early_finish_date"]}
             for r in after["gantt_rows"]], baseline)
    return result
