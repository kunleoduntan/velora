"""Tenant-scoped native schedule reads and approved schedule-change application.

All reads and writes use injected Velora document, transaction, authorization,
audit and idempotency ports. No local persistence fallback is provided.
"""
from __future__ import annotations

import json
from hashlib import sha256
from copy import deepcopy

from ..services.advanced_schedule import calculate_gantt, preview_schedule_change
from ..services.calendar import working_days_between

def _validate_calendar(working_weekdays, holidays):
    days = tuple(working_weekdays)
    if not days or len(set(days)) != len(days) or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 or x > 6 for x in days):
        raise ValueError("working_weekdays must contain unique weekday integers from 0 to 6.")
    if not isinstance(holidays, (list, tuple, set)):
        raise ValueError("holidays must be a list of ISO dates.")
    from datetime import date
    for item in holidays:
        try: date.fromisoformat(str(item))
        except ValueError as exc: raise ValueError("holidays must contain ISO YYYY-MM-DD dates.") from exc
    return days, tuple(str(x) for x in holidays)


RELATIONSHIPS = {
    "Finish to Start": "FS", "Start to Start": "SS",
    "Finish to Finish": "FF", "Start to Finish": "SF",
    "FS": "FS", "SS": "SS", "FF": "FF", "SF": "SF",
}


def _json_snapshot(value):
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError("Approved baseline schedule_snapshot is not valid JSON.") from exc
    if isinstance(parsed, dict):
        parsed = parsed.get("tasks", parsed.get("activities", parsed.get("gantt_rows", [])))
    if not isinstance(parsed, list):
        raise ValueError("Approved baseline snapshot must contain a task list.")
    rows = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Approved baseline contains an invalid task row.")
        task_id = item.get("id") or item.get("task") or item.get("task_id")
        start = item.get("start_date") or item.get("planned_start") or item.get("early_start_date")
        finish = item.get("finish_date") or item.get("planned_finish") or item.get("early_finish_date")
        if task_id and start and finish:
            rows.append({"id": str(task_id), "start_date": str(start), "finish_date": str(finish)})
    return rows


def _calendar_from_project(repository, actor, project):
    """Resolve the explicit project calendar or the unique active company default."""
    calendar_id = project.get("resource_calendar")
    if calendar_id:
        calendar = repository.get(actor, "Resource Calendar", calendar_id)
        if not calendar or not calendar.get("active", 1):
            raise ValueError("The project's selected Resource Calendar is missing or inactive.")
        return calendar
    try:
        calendars = repository.list(actor, "Resource Calendar", filters={"active": 1, "is_default": 1}, limit=100)
    except (KeyError, ValueError, TypeError):
        return None
    if len(calendars) > 1:
        raise ValueError("Multiple active default Resource Calendars exist; select one on the project.")
    return calendars[0] if calendars else None


def _parse_holidays(value):
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = [part.strip() for part in value.replace(",", "\n").splitlines() if part.strip()]
    else:
        parsed = value
    if not isinstance(parsed, (list, tuple)):
        raise ValueError("Resource Calendar holiday_dates must be a JSON array or a line-separated list.")
    from datetime import date
    result = []
    for item in parsed:
        try:
            iso = date.fromisoformat(str(item)).isoformat()
        except ValueError as exc:
            raise ValueError("Resource Calendar holidays must use ISO YYYY-MM-DD dates.") from exc
        if iso in result:
            raise ValueError("Resource Calendar holiday dates must be unique.")
        result.append(iso)
    return tuple(result)


def validate_dependency_graph(tasks, dependencies, candidate, *, exclude_id=None):
    """Validate a proposed dependency mutation against the complete project DAG."""
    activities = []
    for task in tasks:
        duration = task.get("duration_days", 0)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError(f"Task {task.get('name')} has an invalid duration_days value.")
        activities.append({"id": str(task.get("name")), "name": task.get("title"),
                           "duration": duration, "dependencies": []})
    by_id = {row["id"]: row for row in activities}
    task_ids = set(by_id)
    edges = [dict(row) for row in dependencies if str(row.get("name")) != str(exclude_id)]
    edges.append(dict(candidate))
    for edge in edges:
        pred, succ = str(edge.get("predecessor") or ""), str(edge.get("successor") or "")
        if pred not in task_ids or succ not in task_ids or pred == succ:
            raise ValueError("Both dependency tasks must be distinct tasks in the selected project.")
        rel = RELATIONSHIPS.get(edge.get("relationship"), None)
        if rel is None:
            raise ValueError("Unsupported dependency relationship.")
        lag = edge.get("lag_days", 0)
        if isinstance(lag, bool) or not isinstance(lag, int):
            raise ValueError("Dependency lag must be an integer working-day value.")
        if edge.get("active", 1):
            by_id[succ]["dependencies"].append({"predecessor": pred, "type": rel, "lag": lag})
    # CPM validation includes duplicate, reference and cycle checks.
    from ..services.advanced_schedule import calculate_cpm
    calculate_cpm(activities)
    return True


def build_live_schedule(repository, actor, project_id, *, working_weekdays=None, holidays=None):
    """Load a project, its tasks/dependencies and current approved baseline."""
    project = repository.get(actor, "Project", project_id)
    if project is None:
        raise KeyError(project_id)
    calendar = _calendar_from_project(repository, actor, project)
    if working_weekdays is None:
        raw_days = (calendar or {}).get("working_weekdays", "0,1,2,3,4")
        if isinstance(raw_days, str):
            try: working_weekdays = tuple(int(x.strip()) for x in raw_days.split(",") if x.strip())
            except ValueError as exc: raise ValueError("Resource Calendar working_weekdays must be comma-separated weekday numbers.") from exc
        else:
            working_weekdays = tuple(raw_days)
    if holidays is None:
        holidays = _parse_holidays((calendar or {}).get("holiday_dates"))
    working_weekdays, holidays = _validate_calendar(working_weekdays, holidays)
    start = project.get("start_date")
    if not start:
        raise ValueError("Project planned start date is required before schedule calculation.")
    tasks = repository.list(actor, "Project Task", filters={"project": project_id}, limit=500)
    if not tasks:
        raise ValueError("The selected project has no Project Task records.")
    dependencies = repository.list(actor, "Task Dependency", filters={"project": project_id}, limit=500)
    task_ids = {str(t.get("name")) for t in tasks}
    activities = []
    for task in tasks:
        task_id = str(task.get("name") or "")
        if not task_id:
            raise ValueError("A Project Task record has no stable name.")
        duration = task.get("duration_days", 0)
        if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
            raise ValueError(f"Task {task_id} has an invalid duration_days value.")
        planned_start = task.get("planned_start")
        offset = 0
        if planned_start:
            offset = max(0, working_days_between(start, planned_start, working_weekdays, holidays) - 1)
        activities.append({
            "id": task_id, "name": task.get("title") or task.get("task_code") or task_id,
            "wbs": task.get("wbs"), "duration": duration,
            "planned_start_offset": offset, "assignee": task.get("assignee"),
            "status": task.get("status", "Draft"),
            "progress_percent": task.get("progress_percent", 0),
            "version": task.get("version"),
        })
    for dep in dependencies:
        if not dep.get("active", 1):
            continue
        pred, succ = str(dep.get("predecessor") or ""), str(dep.get("successor") or "")
        if pred not in task_ids or succ not in task_ids:
            raise ValueError("A task dependency references a task outside the selected project.")
        relationship = RELATIONSHIPS.get(dep.get("relationship"), None)
        if relationship is None:
            raise ValueError(f"Unsupported dependency relationship: {dep.get('relationship')}")
        target = next(row for row in activities if row["id"] == succ)
        target.setdefault("dependencies", []).append({
            "predecessor": pred, "type": relationship,
            "lag": dep.get("lag_days", 0),
        })
    baselines = repository.list(actor, "Project Baseline", filters={
        "project": project_id, "approval_status": "Approved", "is_current": 1,
    }, limit=100)
    baseline_rows = []
    if baselines:
        if len(baselines) > 1:
            raise ValueError("Multiple current approved baselines exist; resolve the baseline control before scheduling.")
        baseline_rows = _json_snapshot(baselines[0].get("schedule_snapshot"))
    schedule = calculate_gantt(activities, start, working_weekdays, holidays)
    task_by_id = {str(t["name"]): t for t in tasks}
    return {
        "project": {"name": project_id, "title": project.get("project_name") or project.get("title"),
                    "start_date": start, "end_date": project.get("end_date")},
        "activities": activities, "schedule": schedule,
        "tasks_by_id": task_by_id, "dependencies": dependencies, "baseline": baseline_rows,
        "baseline_name": baselines[0].get("baseline_name") if baselines else None,
        "calendar": {"name": (calendar or {}).get("name"),
                     "calendar_name": (calendar or {}).get("calendar_name", "Default Monday-Friday"),
                     "working_weekdays": list(working_weekdays), "holidays": list(holidays)},
        "read_only": True, "source": "Velora native Project and Project Task documents",
    }


def create_schedule_change_request(bridge, actor, project_id, *, task_id, proposed_start_offset,
                                   reason, title, idempotency_key,
                                   working_weekdays=None, holidays=None):
    """Create an impact-backed change request and submit it to host workflow."""
    if not isinstance(reason, str) or len(reason.strip()) < 10:
        raise ValueError("A schedule-change reason of at least 10 characters is required.")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("A schedule-change title is required.")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
        raise ValueError("A valid idempotency_key (1-128 characters) is required.")
    bridge.assert_permission(actor, "projectone.task.update", project_id=project_id)
    repo = bridge.document_repository()
    live = build_live_schedule(repo, actor, project_id,
                               working_weekdays=working_weekdays, holidays=holidays)
    working_weekdays = tuple(live["calendar"]["working_weekdays"])
    holidays = tuple(live["calendar"]["holidays"])
    preview = preview_schedule_change(live["activities"], live["project"]["start_date"],
        task_id, proposed_start_offset, working_weekdays, holidays,
        baseline=live["baseline"] or None)
    proposed = {r["id"]: r for r in preview["schedule"]["gantt_rows"]}
    updates = []
    for impact in preview["impacts"]:
        task = live["tasks_by_id"][impact["task_id"]]
        row = proposed[impact["task_id"]]
        updates.append({"task": impact["task_id"], "expected_version": task.get("version"),
                        "planned_start": row["early_start_date"],
                        "planned_finish": row["early_finish_date"]})
    if not updates:
        raise ValueError("The proposed constraint does not change any task dates; no change request is required.")
    payload = {"project": project_id, "task_updates": updates,
               "preview_project_finish": preview["proposed_project_finish"],
               "previous_project_finish": preview["previous_project_finish"],
               "finish_variance_calendar_days": preview["project_finish_variance_calendar_days"]}
    clean_code = "".join(ch for ch in idempotency_key if ch.isalnum())[:40] or "CHANGE"
    doc = repo.insert(actor, "Project Change Request", {
        "project": project_id, "change_code": f"SCH-{clean_code}",
        "title": title.strip(), "reason": reason.strip(),
        "scope_impact": "Schedule-only change generated from the native task schedule preview.",
        "schedule_impact_days": preview["project_finish_variance_calendar_days"],
        "resource_impact": "No resource reservations are created by this request.",
        "risk_impact": "Review task dependencies, critical path and resource capacity before approval.",
        "requested_by": actor.actor_id,
    }, idempotency_key=idempotency_key,
       trusted_fields={"schedule_change_payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
                       "schedule_applied": 0})
    if doc.get("approval_status") == "Draft":
        workflow = bridge.workflow_action(actor, "Project Change Request", doc["name"],
                                          "submit_for_approval", {"reason": reason.strip()})
        # Re-read through the tenant-scoped repository; workflow owns the state transition.
        doc = repo.get(actor, "Project Change Request", doc["name"]) or doc
    else:
        workflow = {"status": "already_submitted", "approval_status": doc.get("approval_status")}
    return {"change_request": doc, "workflow": workflow, "preview": preview,
            "persisted_schedule_changes": False,
            "message": "Change request submitted; task dates remain unchanged until approval and application."}


def apply_approved_schedule_change(bridge, actor, change_request_name):
    """Atomically apply an approved schedule request with version checks and audit."""
    from ..integrations.native_documents import CORE_DOCUMENTS
    if "Project Change Request" not in CORE_DOCUMENTS:
        raise RuntimeError("Project Change Request persistence is not enabled.")
    repo = bridge.document_repository()
    request = repo.get(actor, "Project Change Request", change_request_name)
    if request is None:
        raise KeyError(change_request_name)
    if request.get("approval_status") != "Approved":
        raise ValueError("Only an approved schedule change request can be applied.")
    project_id = request.get("project")
    bridge.assert_permission(actor, "projectone.schedule.apply", project_id=project_id)
    bridge.assert_permission(actor, "projectone.task.update", project_id=project_id)
    if request.get("schedule_applied"):
        return {"change_request": change_request_name, "applied": True, "replayed": True, "updated_tasks": []}
    try:
        payload = json.loads(request.get("schedule_change_payload") or "{}")
    except ValueError as exc:
        raise ValueError("Approved schedule change payload is invalid JSON.") from exc
    updates = payload.get("task_updates")
    if not isinstance(updates, list) or not updates:
        raise ValueError("Approved schedule change contains no task updates.")
    task_ids = [item.get("task") for item in updates if isinstance(item, dict)]
    if len(task_ids) != len(updates) or len(set(task_ids)) != len(task_ids) or any(not x for x in task_ids):
        raise ValueError("Approved schedule change contains duplicate or invalid task identifiers.")
    from datetime import date
    for item in updates:
        try:
            start_date = date.fromisoformat(str(item["planned_start"]))
            finish_date = date.fromisoformat(str(item["planned_finish"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Approved schedule task dates must be valid ISO dates.") from exc
        if finish_date < start_date:
            raise ValueError("Approved schedule task finish cannot precede its start.")
    digest = sha256(json.dumps({"request": change_request_name, "payload": payload},
                               sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    engine, uow, audit, idem = bridge.document_engine, bridge.transaction_manager, bridge.audit_service, bridge.idempotency_store
    applied_rows = []
    with uow.transaction() as session:
        def operation():
            nonlocal applied_rows
            current_request = engine.get(session, "Project Change Request", change_request_name, actor.company_id)
            if not current_request or current_request.get("approval_status") != "Approved":
                raise ValueError("The schedule change request is no longer approved.")
            if current_request.get("schedule_applied"):
                return {"change_request": change_request_name, "applied": True, "replayed": True, "updated_tasks": []}
            for item in updates:
                task_id = item.get("task")
                before = engine.get(session, "Project Task", task_id, actor.company_id)
                if not before or before.get("project") != project_id:
                    raise ValueError(f"Task {task_id} is missing or outside the approved project.")
                expected = item.get("expected_version")
                if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1 or before.get("version") != expected:
                    from ..services.persistence import VersionConflict
                    raise VersionConflict(f"Task {task_id} changed after the schedule request; refresh and resubmit.")
                safe = {"planned_start": item["planned_start"], "planned_finish": item["planned_finish"]}
                after = engine.update_if_version(session, "Project Task", task_id, actor.company_id,
                                                 safe, expected, actor.actor_id)
                audit.append(session, company_id=actor.company_id, project_id=project_id,
                             actor_id=actor.actor_id, action="project_task.approved_schedule_change_applied",
                             before=before, after=after)
                applied_rows.append(task_id)
            req_after = engine.update_if_version(session, "Project Change Request", change_request_name,
                actor.company_id, {"schedule_applied": 1}, current_request.get("version"), actor.actor_id)
            audit.append(session, company_id=actor.company_id, project_id=project_id,
                         actor_id=actor.actor_id, action="project_change_request.schedule_applied",
                         before=current_request, after=req_after)
            return {"change_request": change_request_name, "applied": True,
                    "replayed": False, "updated_tasks": list(applied_rows)}
        result = idem.execute(session, actor.company_id,
            f"projectone:schedule-apply:{change_request_name}", digest, operation)
    return deepcopy(result)
