"""Pure executive sustainability reporting dashboard aggregation."""
from collections import Counter, defaultdict


def build_reporting_dashboard(periods, assessments, tasks, reports, reviews=None, framework_by_disclosure=None):
    """Aggregate dashboard metrics; all inputs are permission-filtered by the caller."""
    framework_by_disclosure = framework_by_disclosure or {}
    period_ids = {p.get("name") for p in periods}
    assessments = [a for a in assessments if a.get("reporting_period") in period_ids]
    tasks = [t for t in tasks if t.get("reporting_period") in period_ids]
    period_names = {p.get("period_name") for p in periods}
    reports = [r for r in reports if r.get("reporting_period") in period_names or r.get("reporting_period") in period_ids]
    reviews = reviews or []
    review_counts = Counter(r.get("review_status") or "Pending" for r in reviews)
    applicable = [a for a in assessments if a.get("applicable") and a.get("assessment_status") != "Not Applicable"]
    ready = [a for a in applicable if a.get("assessment_status") in ("Ready", "Reviewed")]
    status_counts = Counter(a.get("assessment_status") or "Not Started" for a in assessments)
    task_counts = Counter(t.get("task_status") or "Open" for t in tasks)
    total = len(applicable)
    readiness = round(sum(float(a.get("readiness_percent") or 0) for a in applicable) / total, 2) if total else 0
    gaps = [a for a in applicable if a.get("assessment_status") not in ("Ready", "Reviewed")]
    missing = [{"disclosure": a.get("disclosure"), "status": a.get("assessment_status"),
                "readiness_percent": a.get("readiness_percent", 0), "gap_summary": a.get("gap_summary"),
                "owner": a.get("disclosure_owner") or a.get("owner"), "due_date": a.get("due_date"),
                "framework": framework_by_disclosure.get(a.get("disclosure"))} for a in gaps]
    period_rows = []
    framework_rollups = defaultdict(lambda: {"disclosures_total": 0, "disclosures_ready": 0, "readiness_sum": 0.0})
    owner_rollups = defaultdict(lambda: {"tasks_total": 0, "tasks_completed": 0, "tasks_overdue": 0})
    for p in periods:
        p_assessments = [a for a in assessments if a.get("reporting_period") == p.get("name") and a.get("applicable") and a.get("assessment_status") != "Not Applicable"]
        p_ready = sum(a.get("assessment_status") in ("Ready", "Reviewed") for a in p_assessments)
        p_tasks = [t for t in tasks if t.get("reporting_period") == p.get("name")]
        p_readiness = round(sum(float(a.get("readiness_percent") or 0) for a in p_assessments)/len(p_assessments), 2) if p_assessments else 0
        period_rows.append({"name": p.get("name"), "period_name": p.get("period_name"), "period_status": p.get("period_status"),
            "owner": p.get("period_owner") or p.get("owner"), "disclosures_total": len(p_assessments), "disclosures_ready": p_ready,
            "readiness_percent": p_readiness, "tasks_total": len(p_tasks),
            "tasks_completed": sum(t.get("task_status") == "Completed" for t in p_tasks),
            "tasks_overdue": sum(t.get("task_status") == "Overdue" for t in p_tasks)})
        for a in p_assessments:
            framework = framework_by_disclosure.get(a.get("disclosure")) or "Unmapped"
            f = framework_rollups[framework]
            f["disclosures_total"] += 1
            f["disclosures_ready"] += int(a.get("assessment_status") in ("Ready", "Reviewed"))
            f["readiness_sum"] += float(a.get("readiness_percent") or 0)
        for task in p_tasks:
            owner = task.get("responsible_owner") or "Unassigned"
            o = owner_rollups[owner]
            o["tasks_total"] += 1
            o["tasks_completed"] += int(task.get("task_status") == "Completed")
            o["tasks_overdue"] += int(task.get("task_status") == "Overdue")
    framework_summary = [{"framework": name, **vals,
        "readiness_percent": round(vals["readiness_sum"] / vals["disclosures_total"], 2) if vals["disclosures_total"] else 0}
        for name, vals in sorted(framework_rollups.items())]
    owner_summary = [{"owner": name, **vals} for name, vals in sorted(owner_rollups.items())]
    return {"periods": len(periods), "disclosures_total": total, "disclosures_ready": len(ready),
        "disclosures_with_gaps": len(gaps), "readiness_percent": readiness,
        "assessment_status_counts": dict(status_counts), "task_status_counts": dict(task_counts),
        "tasks_total": len(tasks), "tasks_completed": task_counts.get("Completed", 0),
        "tasks_overdue": task_counts.get("Overdue", 0), "reports_total": len(reports),
        "review_status_counts": dict(review_counts),
        "reviews_pending": review_counts.get("Pending", 0) + review_counts.get("In Progress", 0),
        "reviews_returned": review_counts.get("Returned for Changes", 0) + review_counts.get("Rejected", 0),
        "reviews_completed": review_counts.get("Completed", 0), "missing_disclosures": missing,
        "period_summary": period_rows, "framework_summary": framework_summary, "owner_summary": owner_summary}
