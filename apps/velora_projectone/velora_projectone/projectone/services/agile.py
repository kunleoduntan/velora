"""Agile delivery controls: backlog readiness, sprint planning, Kanban and metrics.

Pure domain services only. Persistence, authentication, authorization and workflow
execution remain responsibilities of the Velora host application.
"""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

STORY_STATES = {"Draft", "Open", "Ready", "In Progress", "In Review", "Done", "Blocked", "Cancelled"}
SPRINT_STATES = {"Draft", "Planned", "Active", "Review", "Completed", "Cancelled"}
KANBAN_COLUMNS = ("Backlog", "Ready", "In Progress", "In Review", "Done")


def _decimal(value, label, *, minimum=Decimal("0")):
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be numeric.")
    if not number.is_finite() or number < minimum:
        raise ValueError(f"{label} must be finite and at least {minimum}.")
    return number


def validate_story(story, *, require_ready=False):
    if not isinstance(story, dict):
        raise ValueError("Story must be an object.")
    key = str(story.get("story_id") or story.get("story_key") or "").strip()
    title = str(story.get("title") or "").strip()
    if not key or not title:
        raise ValueError("Story key and title are required.")
    points = _decimal(story.get("story_points", 0), "Story points")
    criteria = str(story.get("acceptance_criteria") or "").strip()
    state = story.get("status", "Draft")
    if state not in STORY_STATES:
        raise ValueError(f"Unsupported story status: {state}")
    ready_checks = {
        "acceptance_criteria": bool(criteria),
        "estimate": points > 0,
        "assignee": bool(story.get("assignee")),
        "priority": bool(story.get("priority")),
        "dependencies_assessed": story.get("dependencies_assessed") is True,
    }
    ready = all(ready_checks.values())
    done_checks = {
        "acceptance_criteria_met": story.get("acceptance_criteria_met") is True,
        "reviewed": story.get("reviewed") is True,
        "tests_passed": story.get("tests_passed") is True,
        "documentation_updated": story.get("documentation_updated") is True,
    }
    done = all(done_checks.values())
    if require_ready and not ready:
        missing = [name for name, passed in ready_checks.items() if not passed]
        raise ValueError("Story does not meet Definition of Ready: " + ", ".join(missing))
    return {"story_id": key, "story_points": points, "status": state,
            "definition_of_ready": ready, "ready_checks": ready_checks,
            "definition_of_done": done, "done_checks": done_checks}


def validate_sprint(sprint, stories):
    if not sprint.get("sprint_id") or not sprint.get("start_date") or not sprint.get("end_date"):
        raise ValueError("Sprint ID, start date and end date are required.")
    try:
        start, end = date.fromisoformat(str(sprint["start_date"])), date.fromisoformat(str(sprint["end_date"]))
    except ValueError:
        raise ValueError("Sprint dates must use ISO YYYY-MM-DD format.")
    if end < start:
        raise ValueError("Sprint end date cannot precede start date.")
    ids, total = set(), Decimal("0")
    for story in stories:
        result = validate_story(story)
        sid = result["story_id"]
        if sid in ids:
            raise ValueError("User story IDs must be present and unique within the sprint.")
        ids.add(sid)
        total += result["story_points"]
    capacity = _decimal(sprint.get("capacity_points", sprint.get("committed_points", total)), "Sprint capacity")
    if total > capacity:
        raise ValueError(f"Sprint commitment ({total}) exceeds point capacity ({capacity}).")
    return {"sprint_id": sprint["sprint_id"], "planned_story_points": total,
            "story_count": len(ids), "capacity_points": capacity,
            "remaining_capacity": capacity-total, "capacity_utilisation": total/capacity if capacity else None}


def sprint_metrics(stories):
    planned = done = Decimal("0")
    blocked = unaccepted = 0
    for story in stories:
        points = _decimal(story.get("story_points", 0), "Story points")
        planned += points
        if story.get("status") == "Done" and story.get("accepted") is True:
            done += points
        elif story.get("status") == "Done":
            unaccepted += 1
        if story.get("status") == "Blocked":
            blocked += 1
    unaccepted_points = sum((_decimal(s.get("story_points", 0), "Story points") for s in stories
                             if s.get("status") == "Done" and s.get("accepted") is not True), Decimal("0"))
    return {"planned_points": planned, "accepted_points": done,
            "completion_ratio": done/planned if planned else None,
            "blocked_story_count": blocked, "unaccepted_done_points": unaccepted_points,
            "unaccepted_done_story_count": unaccepted,
            "remaining_points": planned-done}


def plan_sprint(sprint, backlog, *, team_capacity_hours=None):
    """Select ranked Ready stories without exceeding capacity; never silently drops items."""
    validation = validate_sprint({**sprint, "capacity_points": sprint.get("capacity_points", sprint.get("committed_points", 0))}, [])
    capacity = validation["capacity_points"]
    hours_capacity = None if team_capacity_hours is None else _decimal(team_capacity_hours, "Team capacity hours")
    selected, deferred, points, hours = [], [], Decimal("0"), Decimal("0")
    ordered = sorted(backlog, key=lambda x: (int(x.get("backlog_rank", 999999)), str(x.get("story_id") or x.get("story_key") or "")))
    seen = set()
    for story in ordered:
        checked = validate_story(story, require_ready=True)
        sid = checked["story_id"]
        if sid in seen:
            raise ValueError(f"Duplicate backlog story: {sid}")
        seen.add(sid)
        estimate_hours = _decimal(story.get("estimated_hours", 0), f"{sid} estimated hours")
        if points + checked["story_points"] <= capacity and (hours_capacity is None or hours+estimate_hours <= hours_capacity):
            selected.append(sid); points += checked["story_points"]; hours += estimate_hours
        else:
            deferred.append({"story_id": sid, "reason": "Sprint capacity exceeded"})
    return {"sprint_id": sprint["sprint_id"], "selected_story_ids": selected,
            "deferred": deferred, "committed_points": points,
            "estimated_hours": hours, "remaining_points": capacity-points,
            "remaining_hours": None if hours_capacity is None else hours_capacity-hours}


def kanban_board(stories, *, wip_limits=None):
    wip_limits = wip_limits or {}
    columns = {name: [] for name in KANBAN_COLUMNS}
    mapping = {"Draft": "Backlog", "Open": "Backlog", "Ready": "Ready", "In Progress": "In Progress",
               "In Review": "In Review", "Done": "Done", "Blocked": "In Progress", "Cancelled": "Backlog"}
    for story in stories:
        checked = validate_story(story)
        column = mapping[checked["status"]]
        columns[column].append({"story_id": checked["story_id"], "title": story["title"],
                                "story_points": checked["story_points"], "assignee": story.get("assignee"),
                                "priority": story.get("priority", "Normal"),
                                "blocked": checked["status"] == "Blocked"})
    for name, rows in columns.items():
        rows.sort(key=lambda x: (x["priority"] not in ("Critical", "High"), str(x["story_id"])))
    return {"columns": [{"name": name, "items": rows, "count": len(rows),
                         "wip_limit": wip_limits.get(name),
                         "wip_exceeded": name in wip_limits and len(rows) > int(wip_limits[name])}
                        for name, rows in columns.items()]}


def burndown(sprint, stories, *, daily_completed=None):
    """Return ideal and actual remaining points for each sprint calendar day.

    daily_completed is a trusted, persisted daily aggregate keyed by ISO date;
    this function does not infer history from current story status.
    """
    try:
        start, end = date.fromisoformat(str(sprint["start_date"])), date.fromisoformat(str(sprint["end_date"]))
    except (KeyError, ValueError):
        raise ValueError("Valid sprint start_date and end_date are required.")
    if end < start:
        raise ValueError("Sprint end date cannot precede start date.")
    total = sum((_decimal(s.get("story_points", 0), "Story points") for s in stories), Decimal("0"))
    daily_completed = daily_completed or {}
    days = (end-start).days + 1
    cumulative = Decimal("0")
    points = []
    for index in range(days):
        day = start + timedelta(days=index)
        completed = _decimal(daily_completed.get(day.isoformat(), 0), "Daily completed points")
        cumulative += completed
        remaining = max(Decimal("0"), total-cumulative)
        ideal = total * Decimal(days-index-1) / Decimal(max(days-1, 1)) if days > 1 else Decimal("0")
        points.append({"date": day.isoformat(), "ideal_remaining": ideal,
                       "actual_remaining": remaining, "completed_today": completed})
    return {"total_points": total, "points": points,
            "actual_history_source": "persisted daily accepted-story completion aggregates"}


def sprint_review(stories):
    metrics = sprint_metrics(stories)
    accepted = [s.get("story_id") or s.get("story_key") for s in stories
                if s.get("status") == "Done" and s.get("accepted") is True]
    carried = [s.get("story_id") or s.get("story_key") for s in stories
               if s.get("status") not in ("Done", "Cancelled") or (s.get("status") == "Done" and s.get("accepted") is not True)]
    return {"metrics": metrics, "accepted_stories": accepted, "carried_forward_stories": carried,
            "review_required": True, "review_recorded": False}


def validate_retrospective(retrospective):
    required = ("sprint_id", "facilitator", "what_went_well", "what_to_improve", "actions")
    missing = [key for key in required if not retrospective.get(key)]
    if missing:
        raise ValueError("Retrospective is incomplete: " + ", ".join(missing))
    actions = retrospective.get("actions")
    if not isinstance(actions, list) or any(not isinstance(a, dict) or not a.get("owner") or not a.get("due_date") or not a.get("action") for a in actions):
        raise ValueError("Each retrospective action requires action, owner and due_date.")
    for action in actions:
        try: date.fromisoformat(str(action["due_date"]))
        except ValueError: raise ValueError("Retrospective action due dates must use ISO YYYY-MM-DD format.")
    return {"valid": True, "action_count": len(actions), "sprint_id": retrospective["sprint_id"]}


def transition_story(story, new_status):
    """Validate a story status transition and return a changed copy."""
    from copy import deepcopy
    allowed = {
        "Draft": {"Open", "Cancelled"}, "Open": {"Ready", "Cancelled"},
        "Ready": {"In Progress", "Cancelled"}, "In Progress": {"In Review", "Blocked", "Cancelled"},
        "Blocked": {"In Progress", "Cancelled"}, "In Review": {"In Progress", "Done", "Blocked"},
        "Done": {"In Progress"}, "Cancelled": set(),
    }
    current = story.get("status", "Draft")
    if new_status not in allowed.get(current, set()):
        raise ValueError(f"Invalid story transition: {current} -> {new_status}")
    if new_status == "Ready":
        validate_story({**story, "status": "Ready"}, require_ready=True)
    if new_status == "Done":
        checks = validate_story({**story, "status": "In Review"})["done_checks"]
        if not all(checks.values()):
            raise ValueError("Story cannot be Done until Definition of Done is satisfied: " + ", ".join(k for k,v in checks.items() if not v))
    updated = deepcopy(story)
    updated["status"] = new_status
    if current == "Done" and new_status == "In Progress":
        updated["accepted"] = False
    return updated
