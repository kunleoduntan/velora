"""Permission-filtered enterprise dashboard read models for ProjectOne.

All inputs must already be scoped by the host's authenticated company and row policy.
These builders are pure projections: they never persist or post transactions.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation


def _d(value, field="amount"):
    try:
        result = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric.")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result


def _rows(data, key):
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list.")
    return value


def _count(rows, field):
    return dict(Counter(str(r.get(field) or "Unspecified") for r in rows))


def _top(rows, key, limit=10, reverse=True):
    return sorted(rows, key=lambda x: _d(x.get(key)), reverse=reverse)[:limit]


def _money_sum(rows, field):
    return sum((_d(r.get(field), field) for r in rows), Decimal("0"))


def portfolio_dashboard(data):
    projects = _rows(data, "projects")
    positions = _rows(data, "project_positions")
    for project in projects:
        for field in ("approved_budget", "actual_cost", "open_commitments"):
            if project.get(field) is not None:
                _d(project.get(field), field)
    groups = {}
    by_currency = {}
    for row in positions:
        currency = str(row.get("currency") or "").strip()
        if currency:
            by_currency.setdefault(currency, []).append(row)
    for currency, rows in by_currency.items():
        def complete_sum(field):
            return _money_sum(rows, field) if rows and all(row.get(field) is not None for row in rows) else None
        budget = complete_sum("approved_budget")
        actual_cost = complete_sum("actual_cost")
        commitments = complete_sum("open_commitments")
        forecast_cost = complete_sum("estimate_at_completion")
        groups[currency] = {"projects": len(rows), "budget": budget,
            "actual_cost": actual_cost, "open_commitments": commitments,
            "forecast_cost": forecast_cost,
            "available_budget": budget - actual_cost - commitments
                if budget is not None and actual_cost is not None and commitments is not None else None}
    kpis = {
        "projects": len(projects),
        "active": sum(1 for p in projects if p.get("status") in ("In Progress", "Active")),
        "completed": sum(1 for p in projects if p.get("status") == "Completed"),
        "overdue_projects": sum(1 for p in projects if p.get("is_overdue")),
    }
    # Portfolio money totals are only meaningful when all source positions use
    # one explicit currency. Mixed currencies remain in separate groups.
    position_currencies = {str(row.get("currency") or "").strip() for row in positions}
    if positions and len(groups) == 1 and len(position_currencies) == 1 and "" not in position_currencies:
        currency = next(iter(groups))
        group = groups[currency]
        for field, value in (("approved_budget", group["budget"]), ("actual_cost", group["actual_cost"]),
                             ("open_commitments", group["open_commitments"]),
                             ("available_budget", group["available_budget"])):
            if value is not None:
                kpis[field] = value
        if group["actual_cost"] is not None and group["open_commitments"] is not None:
            kpis["forecast_exposure"] = group["actual_cost"] + group["open_commitments"]
        kpis["currency"] = currency
    project_currencies = {str(p.get("currency") or "").strip() for p in projects}
    comparable_project_values = len(project_currencies) == 1 and "" not in project_currencies
    return {"dashboard": "portfolio", "kpis": kpis,
        "currency_groups": groups if groups else {},
        "status_distribution": _count(projects, "status"),
        "projects_by_health": _count(projects, "health"),
        "largest_projects": _top(projects, "approved_budget") if comparable_project_values else [],
        "exceptions": [p for p in projects if p.get("health") in ("Red", "Critical") or p.get("is_overdue")][:20]}


def delivery_dashboard(data):
    tasks = _rows(data, "tasks"); milestones = _rows(data, "milestones"); projects = _rows(data, "projects")
    return {"dashboard": "delivery", "kpis": {
        "total_tasks": len(tasks), "completed_tasks": sum(t.get("status") == "Completed" for t in tasks),
        "in_progress_tasks": sum(t.get("status") == "In Progress" for t in tasks),
        "blocked_tasks": sum(t.get("status") == "Blocked" for t in tasks),
        "overdue_tasks": sum(bool(t.get("is_overdue")) for t in tasks),
        "milestones": len(milestones), "overdue_milestones": sum(bool(m.get("is_overdue")) for m in milestones),
        "projects_behind": sum(p.get("schedule_health") == "Behind" for p in projects)},
        "task_status": _count(tasks, "status"), "milestone_status": _count(milestones, "status"),
        "overdue_items": [x for x in tasks + milestones if x.get("is_overdue")][:30]}


def schedule_dashboard(data):
    tasks = _rows(data, "tasks"); baselines = _rows(data, "baseline_variances")
    critical = [t for t in tasks if t.get("is_critical")]
    schedule_rows = tasks
    if tasks and not data.get("_dependencies_permission_denied"):
        try:
            from ..services.advanced_schedule import calculate_cpm
            activities = [{"id": str(t.get("name") or t.get("task_code") or t.get("title")),
                "name": t.get("title") or t.get("task_code"),
                "duration": max(0, int(float(t.get("duration_days") or 0))),
                "dependencies": t.get("dependencies") or [], "status": t.get("status"),
                "progress_percent": t.get("progress_percent", 0)} for t in tasks]
            cpm = calculate_cpm(activities)
            by_id = {str(t.get("name") or t.get("task_code") or t.get("title")): t for t in tasks}
            schedule_rows = [{**by_id.get(a["id"], {}), **a,
                "is_critical": a["critical"], "total_float_days": a["total_float"]} for a in cpm["activities"]]
            critical = [t for t in schedule_rows if t.get("is_critical")]
        except (ValueError, TypeError, OverflowError):
            schedule_rows = tasks
    return {"dashboard": "schedule", "kpis": {
        "activities": len(tasks), "critical_activities": len(critical),
        "late_activities": sum(bool(t.get("is_late")) for t in tasks),
        "zero_float_activities": sum(_d(t.get("total_float_days")) == 0 for t in schedule_rows if t.get("total_float_days") is not None),
        "average_schedule_variance_days": (sum((_d(x.get("variance_days")) for x in baselines), Decimal("0")) / len(baselines)) if baselines else None},
        "critical_path": critical[:50], "largest_variances": _top(baselines, "variance_days", reverse=True),
        "variance_distribution": _count(baselines, "variance_band")}


def resource_dashboard(data):
    resources = _rows(data, "resources"); allocations = _rows(data, "allocations"); timesheets = _rows(data, "timesheets")
    capacity_known = bool(resources) and all(r.get("available_hours") is not None for r in resources)
    capacity = _money_sum(resources, "available_hours") if capacity_known else None
    allocated = (_money_sum(resources, "allocated_hours") if any(r.get("allocated_hours") is not None for r in resources)
                 else _money_sum(allocations, "planned_hours"))
    return {"dashboard": "resources", "kpis": {
        "resources": len(resources), "available_hours": capacity, "allocated_hours": allocated,
        "utilisation_percent": (allocated / capacity * 100) if capacity_known and capacity else None,
        "overallocated_resources": sum(bool(r.get("is_overallocated")) for r in resources),
        "pending_timesheets": sum(t.get("status") == "Submitted" for t in timesheets),
        "approved_timesheets": sum(t.get("status") == "Approved" for t in timesheets)},
        "resource_type": _count(resources, "resource_type"), "utilisation_by_resource": resources,
        "allocation_conflicts": [a for a in allocations if a.get("is_conflict")][:30]}


def financial_dashboard(data):
    positions = _rows(data, "project_positions")
    currencies = sorted({str(p.get("currency") or "").strip() for p in positions if str(p.get("currency") or "").strip()})
    groups = {}
    for currency in currencies:
        rows = [p for p in positions if str(p.get("currency") or "").strip() == currency]
        groups[currency] = {"projects": len(rows),
            "budget": _money_sum(rows, "approved_budget") if rows and all(p.get("approved_budget") is not None for p in rows) else None,
            "forecast_cost": _money_sum(rows, "estimate_at_completion") if rows and all(p.get("estimate_at_completion") is not None for p in rows) else None}
    # Do not add unlike currencies or treat missing currency/fields as zero.
    totals = {}
    one_currency_complete = len(currencies) == 1 and len(currencies) == len({str(p.get("currency") or "").strip() for p in positions})
    if one_currency_complete:
        for field in ("approved_budget", "actual_cost", "open_commitments", "estimate_to_complete", "estimate_at_completion", "forecast_variance", "recognised_revenue"):
            if positions and all(p.get(field) is not None for p in positions):
                totals[field] = _money_sum(positions, field)
        totals["currency"] = currencies[0]
    return {"dashboard": "financial", "currency_groups": groups, "portfolio_totals": totals if one_currency_complete else None,
        "kpis": {"projects": len(positions), "projects_over_budget": sum(_d(p.get("forecast_variance")) < 0 for p in positions if p.get("forecast_variance") is not None),
                 "projects_with_unfunded_exposure": sum(bool(p.get("unfunded_exposure")) for p in positions)},
        "largest_forecast_overruns": _top(positions, "forecast_overrun") if one_currency_complete else [],
        "positions": positions}


def commercial_dashboard(data):
    contracts = _rows(data, "contracts"); claims = _rows(data, "claims"); variations = _rows(data, "variations"); invoices = _rows(data, "billing_milestones")
    currencies = sorted({str(c.get("currency") or "").strip() for c in contracts if str(c.get("currency") or "").strip()})
    currency_groups = {}
    for currency in currencies:
        rows = [c for c in contracts if str(c.get("currency") or "").strip() == currency]
        def complete_sum(field):
            return _money_sum(rows, field) if rows and all(row.get(field) is not None for row in rows) else None
        currency_groups[currency] = {"contracts": len(rows),
            "contract_value": complete_sum("revised_contract_value"),
            "retention_held": complete_sum("retention_held"),
            "advance_balance": complete_sum("advance_balance")}
    kpis = {"contracts": len(contracts),
        "unapproved_variations": sum(v.get("status") == "Pending" for v in variations),
        "open_claims": sum(c.get("status") in ("Open", "Submitted", "Disputed") for c in claims),
        "unbilled_milestones": sum(m.get("status") not in ("Invoiced", "Paid") for m in invoices)}
    if len(currencies) == 1 and all(str(c.get("currency") or "").strip() == currencies[0] for c in contracts):
        group = currency_groups[currencies[0]]
        for field in ("contract_value", "retention_held", "advance_balance"):
            if group[field] is not None:
                kpis[field] = group[field]
        kpis["currency"] = currencies[0]
    return {"dashboard": "commercial", "kpis": kpis,
        "currency_groups": currency_groups,
        "contract_status": _count(contracts, "status"), "claims_by_status": _count(claims, "status"),
        "commercial_exceptions": [x for x in claims + variations if x.get("is_overdue") or x.get("is_disputed")][:30]}


def risk_dashboard(data):
    risks = _rows(data, "risks"); issues = _rows(data, "issues"); changes = _rows(data, "change_requests")
    return {"dashboard": "risk", "kpis": {
        "risks": len(risks), "critical_risks": sum(r.get("rating") in ("Critical", "Very High") for r in risks),
        "open_issues": sum(i.get("status") not in ("Closed", "Resolved") for i in issues),
        "overdue_actions": sum(bool(x.get("action_overdue")) for x in risks + issues),
        "pending_changes": sum(c.get("status") in ("Draft", "Submitted", "Under Review") for c in changes)},
        "risk_rating": _count(risks, "rating"), "risk_categories": _count(risks, "category"),
        "priority_register": sorted(risks, key=lambda x: (_d(x.get("residual_score")), _d(x.get("inherent_score"))), reverse=True)[:20],
        "open_issues": [i for i in issues if i.get("status") not in ("Closed", "Resolved")][:30]}


def agile_dashboard(data):
    sprints = _rows(data, "sprints"); stories = _rows(data, "stories")
    return {"dashboard": "agile", "kpis": {
        "active_sprints": sum(s.get("status") == "Active" for s in sprints), "planned_sprints": sum(s.get("status") == "Planned" for s in sprints),
        "backlog_stories": sum(s.get("status") in ("Backlog", "Ready") for s in stories),
        "completed_stories": sum(s.get("status") == "Done" for s in stories),
        "blocked_stories": sum(s.get("status") == "Blocked" for s in stories),
        "remaining_story_points": _money_sum([s for s in stories if s.get("status") != "Done"], "story_points")},
        "sprint_status": _count(sprints, "status"), "story_status": _count(stories, "status"),
        "blocked_work": [s for s in stories if s.get("status") == "Blocked"][:30]}


def quality_dashboard(data):
    inspections = _rows(data, "inspections"); deliverables = _rows(data, "deliverables")
    defects = _rows(data, "defects")
    return {"dashboard": "quality", "kpis": {
        "inspections": len(inspections), "failed_inspections": sum(i.get("result") == "Failed" for i in inspections),
        "open_defects": sum(d.get("status") not in ("Closed", "Verified") for d in defects),
        "overdue_defects": sum(bool(d.get("is_overdue")) for d in defects),
        "deliverables_awaiting_acceptance": sum(d.get("status") in ("Submitted", "Under Review") for d in deliverables)},
        "inspection_results": _count(inspections, "result"), "defects_by_severity": _count(defects, "severity"),
        "quality_exceptions": [d for d in defects if d.get("is_overdue") or d.get("severity") in ("Critical", "Major")][:30]}


def programme_dashboard(data):
    programmes = _rows(data, "programmes")
    projects = _rows(data, "projects")
    by_programme = Counter(str(p.get("programme") or "Unassigned") for p in projects)
    exceptions = [p for p in programmes if p.get("status") in ("On Hold", "At Risk", "Delayed")]
    return {"dashboard": "programme", "kpis": {
        "programmes": len(programmes),
        "active_programmes": sum(p.get("status") in ("Active", "In Progress") for p in programmes),
        "completed_programmes": sum(p.get("status") == "Completed" for p in programmes),
        "projects_in_programmes": sum(bool(p.get("programme")) for p in projects),
        "unassigned_projects": sum(not p.get("programme") for p in projects),
        "programme_exceptions": len(exceptions)},
        "programme_status": _count(programmes, "status"),
        "projects_by_programme": dict(by_programme),
        "exceptions": exceptions[:20]}


def benefits_dashboard(data):
    benefits = _rows(data, "benefits")
    realised = [b for b in benefits if str(b.get("realisation_status") or b.get("status") or "").lower() in ("realised", "realized", "completed")]
    at_risk = [b for b in benefits if str(b.get("realisation_status") or b.get("status") or "").lower() in ("at risk", "delayed", "not achieved")]
    gaps = []
    for benefit in benefits:
        target, actual = _d(benefit.get("target_value")), _d(benefit.get("actual_value"))
        gaps.append({**benefit, "benefit_gap": target - actual})
    return {"dashboard": "benefits", "kpis": {
        "benefits": len(benefits), "realised_benefits": len(realised),
        "benefits_at_risk": len(at_risk),
        "benefits_under_target": sum(_d(b.get("actual_value")) < _d(b.get("target_value")) for b in benefits)},
        "benefit_status": _count(benefits, "realisation_status"),
        "largest_benefit_gaps": sorted(gaps, key=lambda b: _d(b.get("benefit_gap")), reverse=True)[:20],
        "at_risk_benefits": at_risk[:20]}


DASHBOARDS = {"portfolio": portfolio_dashboard, "delivery": delivery_dashboard, "schedule": schedule_dashboard,
              "resources": resource_dashboard, "financial": financial_dashboard, "commercial": commercial_dashboard,
              "risk": risk_dashboard, "agile": agile_dashboard, "quality": quality_dashboard,
              "programme": programme_dashboard, "benefits": benefits_dashboard}


def build_dashboard_suite(data):
    if not isinstance(data, dict):
        raise ValueError("Dashboard data must be an object.")
    return {"suite": "ProjectOne Enterprise Dashboards", "dashboards": {name: builder(data) for name, builder in DASHBOARDS.items()},
            "metadata": {"data_scope": "host-permission-filtered", "currency_policy": "never aggregate mixed currencies",
                         "posting_policy": "read-only; source applications remain authoritative"}}
