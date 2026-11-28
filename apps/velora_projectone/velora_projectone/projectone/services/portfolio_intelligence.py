"""Deterministic portfolio prioritisation, scenario and capacity intelligence.

Pure read-model functions. Inputs must already be scoped and authorised by the
Velora host. No function writes project records or accounting ledgers.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from collections import defaultdict


def _d(value, field, *, minimum=None, maximum=None):
    try:
        n = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric.")
    if not n.is_finite():
        raise ValueError(f"{field} must be finite.")
    if minimum is not None and n < Decimal(str(minimum)):
        raise ValueError(f"{field} must be at least {minimum}.")
    if maximum is not None and n > Decimal(str(maximum)):
        raise ValueError(f"{field} must not exceed {maximum}.")
    return n


def prioritise_portfolio(projects, *, weights=None):
    """Score projects on strategic alignment, value, urgency, risk and readiness.

    Each input dimension is 0..100. Weights are configurable, non-negative and
    normalised, so scores remain comparable when weights do not sum to 100.
    """
    if not isinstance(projects, list):
        raise ValueError("projects must be a list.")
    dimensions = ("strategic_alignment", "business_value", "urgency", "risk_reduction", "readiness")
    default = {"strategic_alignment": 30, "business_value": 25, "urgency": 15,
               "risk_reduction": 15, "readiness": 15}
    weights = default if weights is None else weights
    if not isinstance(weights, dict) or set(weights) - set(dimensions):
        raise ValueError("weights contains unsupported scoring dimensions.")
    normalised = {k: _d(weights.get(k, 0), f"weights.{k}", minimum=0) for k in dimensions}
    total_weight = sum(normalised.values(), Decimal("0"))
    if total_weight <= 0:
        raise ValueError("At least one positive scoring weight is required.")
    output, seen = [], set()
    for p in projects:
        if not isinstance(p, dict) or not str(p.get("project_id") or "").strip():
            raise ValueError("Every project requires project_id.")
        pid = str(p["project_id"])
        if pid in seen:
            raise ValueError(f"Duplicate project_id: {pid}.")
        seen.add(pid)
        values = {k: _d(p.get(k, 0), k, minimum=0, maximum=100) for k in dimensions}
        score = sum((values[k] * normalised[k] for k in dimensions), Decimal("0")) / total_weight
        output.append({"project_id": pid, "name": p.get("name", pid), "score": round(score, 2),
                       "dimension_scores": {k: float(v) for k, v in values.items()},
                       "status": p.get("status", "Unspecified")})
    output.sort(key=lambda x: (-x["score"], x["project_id"]))
    for index, row in enumerate(output, 1): row["rank"] = index
    return {"projects": output, "weights": {k: float(v / total_weight * 100) for k, v in normalised.items()},
            "method": "weighted-normalised-score", "source_scope": "caller-authorised-rows-only"}


def model_portfolio_scenario(projects, *, actions, contingency_percent=0):
    """Model explicit defer/cancel/accelerate budget and benefit adjustments.

    Original inputs are not mutated. Values are grouped by currency; no FX is
    inferred. Actions: defer, cancel, accelerate, retain.
    """
    if not isinstance(projects, list) or not isinstance(actions, dict):
        raise ValueError("projects must be a list and actions must be an object.")
    contingency = _d(contingency_percent, "contingency_percent", minimum=0, maximum=100) / 100
    action_map = {"defer", "cancel", "accelerate", "retain"}
    rows, totals, seen = [], defaultdict(lambda: {"baseline_budget": Decimal(0), "scenario_budget": Decimal(0),
        "baseline_benefit": Decimal(0), "scenario_benefit": Decimal(0), "baseline_exposure": Decimal(0),
        "scenario_exposure": Decimal(0), "deferred_budget": Decimal(0),
        "deferred_benefit": Decimal(0), "deferred_exposure": Decimal(0)}), set()
    for p in projects:
        pid = str(p.get("project_id") or "")
        if not pid or pid in seen: raise ValueError("Every project requires a unique project_id.")
        seen.add(pid)
        action = actions.get(pid, "retain")
        if action not in action_map: raise ValueError(f"Unsupported scenario action for {pid}.")
        currency = str(p.get("currency") or "UNSPECIFIED")
        budget = _d(p.get("approved_budget", 0), f"{pid}.approved_budget", minimum=0)
        benefit = _d(p.get("expected_benefit", 0), f"{pid}.expected_benefit", minimum=0)
        exposure = _d(p.get("forecast_exposure", 0), f"{pid}.forecast_exposure", minimum=0)
        # Defer removes the initiative from the active scenario horizon while
        # preserving its value in explicit deferred totals; cancel removes it
        # from both active and deferred totals.
        factor = Decimal("0") if action in {"cancel", "defer"} else Decimal("1")
        scenario_budget = budget * factor
        scenario_benefit = benefit * factor
        scenario_exposure = exposure * factor
        deferred_budget = budget if action == "defer" else Decimal("0")
        deferred_benefit = benefit if action == "defer" else Decimal("0")
        deferred_exposure = exposure if action == "defer" else Decimal("0")
        if action == "accelerate": scenario_exposure *= (Decimal("1") + contingency)
        t = totals[currency]
        t["baseline_budget"] += budget; t["scenario_budget"] += scenario_budget
        t["baseline_benefit"] += benefit; t["scenario_benefit"] += scenario_benefit
        t["baseline_exposure"] += exposure; t["scenario_exposure"] += scenario_exposure
        t["deferred_budget"] += deferred_budget; t["deferred_benefit"] += deferred_benefit
        t["deferred_exposure"] += deferred_exposure
        rows.append({"project_id": pid, "action": action, "currency": currency,
                     "baseline_budget": budget, "scenario_budget": scenario_budget,
                     "baseline_benefit": benefit, "scenario_benefit": scenario_benefit,
                     "baseline_exposure": exposure, "scenario_exposure": scenario_exposure,
                     "deferred_budget": deferred_budget, "deferred_benefit": deferred_benefit,
                     "deferred_exposure": deferred_exposure})
    return {"projects": rows, "currency_totals": {c: {k: float(v) for k, v in t.items()} for c, t in sorted(totals.items())},
            "contingency_percent": float(contingency * 100), "mutated_source_records": False,
            "currency_policy": "separate-currency-totals; no implicit FX"}


def analyse_cross_project_dependencies(dependencies):
    """Detect cross-project dependency cycles and return a topological order."""
    if not isinstance(dependencies, list): raise ValueError("dependencies must be a list.")
    graph, nodes, seen = defaultdict(set), set(), set()
    for row in dependencies:
        if not isinstance(row, dict): raise ValueError("Each dependency must be an object.")
        source, target = str(row.get("predecessor_project") or ""), str(row.get("successor_project") or "")
        if not source or not target or source == target:
            raise ValueError("Cross-project dependency requires distinct predecessor and successor project IDs.")
        key = (source, target)
        if key in seen: raise ValueError("Duplicate cross-project dependency.")
        seen.add(key); nodes.update(key); graph[source].add(target)
    indegree = {n: 0 for n in nodes}
    for source in graph:
        for target in graph[source]: indegree[target] += 1
    ready = sorted(n for n, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        node = ready.pop(0); order.append(node)
        for target in sorted(graph[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target); ready.sort()
    cyclic = sorted(n for n, degree in indegree.items() if degree > 0)
    return {"valid": not cyclic, "topological_order": order if not cyclic else [],
            "cycle_involved_projects": cyclic, "dependency_count": len(seen),
            "cross_project_only": True}


def forecast_enterprise_capacity(demand, capacity):
    """Aggregate period/resource demand against capacity with over-allocation flags."""
    if not isinstance(demand, list) or not isinstance(capacity, list):
        raise ValueError("demand and capacity must be lists.")
    cap = {}
    for row in capacity:
        key = (str(row.get("resource_id") or ""), str(row.get("period") or ""))
        if not all(key): raise ValueError("Capacity rows require resource_id and period.")
        if key in cap: raise ValueError("Duplicate capacity row for resource and period.")
        cap[key] = _d(row.get("available_hours"), "available_hours", minimum=0)
    used = defaultdict(Decimal)
    projects = defaultdict(set)
    for row in demand:
        key = (str(row.get("resource_id") or ""), str(row.get("period") or ""))
        if not all(key): raise ValueError("Demand rows require resource_id and period.")
        hours = _d(row.get("demand_hours"), "demand_hours", minimum=0)
        used[key] += hours
        if row.get("project_id"): projects[key].add(str(row["project_id"]))
    result = []
    for key in sorted(set(cap) | set(used)):
        available, required = cap.get(key, Decimal(0)), used.get(key, Decimal(0))
        variance = available - required
        result.append({"resource_id": key[0], "period": key[1], "available_hours": float(available),
            "demand_hours": float(required), "variance_hours": float(variance),
            "utilisation_percent": round(float(required / available * 100), 2) if available else (100.0 if required else 0.0),
            "over_allocated": key in cap and required > available, "project_count": len(projects[key]),
            "capacity_missing": key not in cap})
    return {"periods": result, "over_allocated_periods": sum(1 for r in result if r["over_allocated"]),
            "capacity_missing_periods": sum(1 for r in result if r["capacity_missing"]),
            "source_scope": "host-authorised-resource-and-allocation-rows"}


def build_portfolio_exception_register(projects, *, schedule_tolerance_days=10, cost_tolerance_percent=10):
    """Create explainable exceptions from project-level performance indicators."""
    if not isinstance(projects, list): raise ValueError("projects must be a list.")
    schedule_tol = _d(schedule_tolerance_days, "schedule_tolerance_days", minimum=0)
    cost_tol = _d(cost_tolerance_percent, "cost_tolerance_percent", minimum=0, maximum=1000)
    exceptions = []
    for p in projects:
        pid = str(p.get("project_id") or "")
        if not pid: raise ValueError("Every project requires project_id.")
        schedule = _d(p.get("schedule_variance_days", 0), "schedule_variance_days")
        budget = _d(p.get("approved_budget", 0), "approved_budget", minimum=0)
        exposure = _d(p.get("forecast_exposure", 0), "forecast_exposure", minimum=0)
        if schedule > schedule_tol:
            exceptions.append({"project_id": pid, "type": "Schedule", "severity": "High" if schedule > schedule_tol * 2 else "Medium",
                               "metric": "schedule_variance_days", "value": float(schedule), "threshold": float(schedule_tol)})
        if budget and (exposure-budget) / budget * 100 > cost_tol:
            variance = (exposure-budget) / budget * 100
            exceptions.append({"project_id": pid, "type": "Cost Forecast", "severity": "High" if variance > cost_tol * 2 else "Medium",
                               "metric": "forecast_over_budget_percent", "value": round(float(variance), 2), "threshold": float(cost_tol)})
        if p.get("critical_risk_open"):
            exceptions.append({"project_id": pid, "type": "Critical Risk", "severity": "High", "metric": "critical_risk_open", "value": True})
    exceptions.sort(key=lambda x: (0 if x["severity"] == "High" else 1, x["project_id"], x["type"]))
    return {"exceptions": exceptions, "count": len(exceptions),
            "high_count": sum(1 for x in exceptions if x["severity"] == "High"),
            "method": "rule-based-explainable-exceptions"}
