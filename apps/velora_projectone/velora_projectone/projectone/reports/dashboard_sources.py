"""Permission-aware collection of native ProjectOne dashboard records.

Every collection is read through NativeDocumentRepository so the host's DocType,
row, company and permission-level checks remain authoritative. External finance,
HRMS, procurement, sales, inventory and fixed-asset data is added separately by
ProjectOneReadIntegration; no records are written or posted here.
"""
from __future__ import annotations
from datetime import date
import json

CORE_DASHBOARD_DOCTYPES = {
    "projects": "Project",
    "portfolios": "Project Portfolio",
    "programmes": "Project Programme",
    "tasks": "Project Task",
    "dependencies": "Task Dependency",
    "milestones": "Project Milestone",
    "baseline_variances": "Project Baseline",
    "risks": "Project Risk",
    "issues": "Project Issue",
    "change_requests": "Project Change Request",
    "deliverables": "Project Deliverable",
    "inspections": "Project Quality Inspection",
    "sprints": "Project Sprint",
    "stories": "Project User Story",
    "allocations": "Project Resource Allocation",
    "timesheets": "Project Timesheet",
    "resources": "Resource Profile",
    "benefits": "Project Benefit",
    "budgets": "Project Budget",
}

PROJECT_LINKED = {key for key in CORE_DASHBOARD_DOCTYPES if key not in {"projects", "portfolios", "programmes", "resources"}}


def _date_before_today(value):
    if not value:
        return False
    try:
        return date.fromisoformat(str(value)[:10]) < date.today()
    except (TypeError, ValueError):
        return False


def collect_core_dashboard_data(repository, actor, *, project_id=None, limit=500):
    """Collect permitted ProjectOne-native records. Denied doctypes are omitted."""
    if not 1 <= int(limit) <= 500:
        raise ValueError("Dashboard collection limit must be between 1 and 500.")
    data, denied = {}, []
    for collection, doctype in CORE_DASHBOARD_DOCTYPES.items():
        try:
            if collection == "projects" and project_id:
                row = repository.get(actor, doctype, project_id)
                rows = [row] if row else []
            else:
                filters = {"project": project_id} if project_id and collection in PROJECT_LINKED else {}
                if collection == "baseline_variances":
                    filters.update({"approval_status": "Approved", "is_current": 1})
                rows = repository.list(actor, doctype, filters=filters, limit=limit, offset=0)
        except PermissionError:
            denied.append(collection)
            continue
        normalized = []
        for original in rows:
            row = dict(original)
            row["_doctype"] = doctype
            if collection == "tasks":
                row["is_overdue"] = _date_before_today(row.get("planned_finish")) and row.get("status") not in ("Completed", "Cancelled")
                row["is_late"] = row["is_overdue"]
                row["is_critical"] = bool(row.get("is_critical"))
            elif collection == "milestones":
                row["is_overdue"] = _date_before_today(row.get("planned_date")) and row.get("status") not in ("Completed", "Cancelled")
            elif collection == "deliverables":
                row["is_overdue"] = _date_before_today(row.get("due_date")) and row.get("status") not in ("Accepted", "Completed", "Cancelled")
            elif collection == "risks":
                score = row.get("risk_score")
                row["residual_score"] = score if score is not None else 0
                row["inherent_score"] = score if score is not None else 0
                row["rating"] = row.get("rating") or ("Critical" if float(score or 0) >= 20 else "High" if float(score or 0) >= 12 else "Medium" if float(score or 0) >= 6 else "Low")
                row["action_overdue"] = _date_before_today(row.get("target_date")) and row.get("status") not in ("Closed", "Resolved")
            elif collection == "issues":
                row["action_overdue"] = _date_before_today(row.get("target_resolution_date")) and row.get("status") not in ("Closed", "Resolved")
            elif collection == "baseline_variances":
                row["variance_days"] = row.get("variance_days", 0)
                row["variance_band"] = row.get("variance_band", "Not calculated")
            elif collection == "resources":
                # Daily capacity is not a period capacity total. Do not compare
                # it with project allocation hours or invent a utilisation rate.
                row["is_overallocated"] = bool(row.get("is_overallocated"))
            elif collection == "timesheets":
                row["status"] = row.get("status") or row.get("approval_status")
            elif collection == "benefits":
                row["status"] = row.get("realisation_status")
            normalized.append(row)
        data[collection] = normalized
    tasks = data.get("tasks", [])
    task_index = {str(row.get("name")): row for row in tasks if row.get("name")}
    for task in tasks:
        task["dependencies"] = []
    relationship_map = {"Finish to Start": "FS", "Start to Start": "SS",
                        "Finish to Finish": "FF", "Start to Finish": "SF",
                        "FS": "FS", "SS": "SS", "FF": "FF", "SF": "SF"}
    for edge in data.get("dependencies", []):
        successor = task_index.get(str(edge.get("successor") or ""))
        if successor and edge.get("active", 1):
            relationship = relationship_map.get(str(edge.get("relationship") or "FS"))
            if relationship:
                successor["dependencies"].append({
                    "predecessor": str(edge.get("predecessor") or ""),
                    "type": relationship,
                    "lag": int(edge.get("lag_days") or 0),
                })
    if "dependencies" in denied:
        data["_dependencies_permission_denied"] = True
    # Calculate baseline variance only from an approved current baseline and
    # dated current task records. No variance is inferred from a baseline header.
    baseline_docs = data.get("baseline_variances", [])
    variance_rows = []
    if baseline_docs and tasks:
        from ..integrations.native_schedule import _json_snapshot
        from ..services.advanced_schedule import compare_schedule_to_baseline
        projects = {str(row.get("project") or "") for row in tasks}
        for project in projects:
            current = [{"id": str(row.get("name") or ""), "start_date": row.get("planned_start"),
                        "finish_date": row.get("planned_finish")} for row in tasks
                       if str(row.get("project") or "") == project and row.get("planned_start") and row.get("planned_finish")]
            project_baselines = [b for b in baseline_docs if str(b.get("project") or "") == project]
            if not current or len(project_baselines) != 1:
                continue
            baseline = _json_snapshot(project_baselines[0].get("schedule_snapshot"))
            if not baseline:
                continue
            comparison = compare_schedule_to_baseline(current, baseline)
            for row in comparison.get("tasks", []):
                variance = row.get("finish_variance_days")
                if variance is None:
                    continue
                variance_rows.append({**row, "project": project, "variance_days": variance,
                    "variance_band": "Late" if variance > 0 else "Early" if variance < 0 else "On Track"})
    data["baseline_variances"] = variance_rows
    return {"data": data, "permission_denied_collections": denied,
            "metadata": {"native_source": "ProjectOne DocTypes", "read_only": True,
                         "permission_filtered": True, "limit_per_collection": limit}}
