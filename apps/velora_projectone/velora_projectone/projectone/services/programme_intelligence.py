"""v2.15 enterprise programme intelligence and risk simulation.

Pure calculation/read-model services. Inputs must be authorised, tenant-scoped
rows supplied by the host. No accounting, HRMS or project records are written.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from .advanced_schedule import calculate_cpm
from .calendar import add_working_days


def _number(value, field, minimum=0):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric")
    if not n.is_finite() or n < Decimal(str(minimum)):
        raise ValueError(f"{field} is outside the permitted range")
    return n


def programme_calendar_schedule(activities, project_start, working_weekdays=(0, 1, 2, 3, 4), holidays=()):
    """Calendar-position CPM using FS/SS/FF/SF relationships and working-day offsets."""
    try:
        anchor = date.fromisoformat(str(project_start))
    except (TypeError, ValueError):
        raise ValueError("project_start must be ISO YYYY-MM-DD")
    if not isinstance(working_weekdays, (list, tuple)) or not working_weekdays or any(
        isinstance(x, bool) or not isinstance(x, int) or x < 0 or x > 6 for x in working_weekdays
    ) or len(set(working_weekdays)) != len(working_weekdays):
        raise ValueError("working_weekdays must contain unique weekday integers from 0 to 6")
    clean_holidays = []
    for h in holidays or ():
        try: clean_holidays.append(date.fromisoformat(str(h)).isoformat())
        except (TypeError, ValueError): raise ValueError("holidays must contain ISO dates")
    if len(set(clean_holidays)) != len(clean_holidays):
        raise ValueError("holidays must be unique")
    # A project calendar start that falls on a weekend/holiday rolls forward
    # to the first valid working day; offset zero must never land on a holiday.
    from .calendar import is_working_day
    while not is_working_day(anchor, working_weekdays, clean_holidays):
        anchor = date.fromisoformat(add_working_days(anchor.isoformat(), 1, working_weekdays, clean_holidays))
    cpm = calculate_cpm(activities)
    rows = []
    for item in cpm["activities"]:
        start = add_working_days(anchor.isoformat(), item["early_start"], working_weekdays, clean_holidays)
        finish_offset = item["early_finish"] - 1 if item["duration"] else item["early_finish"]
        finish = add_working_days(anchor.isoformat(), finish_offset, working_weekdays, clean_holidays)
        late_start = add_working_days(anchor.isoformat(), item["late_start"], working_weekdays, clean_holidays)
        late_finish_offset = item["late_finish"] - 1 if item["duration"] else item["late_finish"]
        late_finish = add_working_days(anchor.isoformat(), late_finish_offset, working_weekdays, clean_holidays)
        rows.append({**item, "early_start_date": start, "early_finish_date": finish,
                     "late_start_date": late_start, "late_finish_date": late_finish})
    finish_date = max((date.fromisoformat(r["early_finish_date"]) for r in rows), default=anchor)
    return {**cpm, "activities": rows, "project_start": anchor.isoformat(),
            "project_finish": finish_date.isoformat(), "working_weekdays": list(working_weekdays),
            "holidays": sorted(clean_holidays), "date_basis": "working calendar with explicit holidays",
            "dependency_types": ["FS", "SS", "FF", "SF"]}


def programme_cost_resource_position(projects):
    """Aggregate cost and resource demand/capacity by currency and resource."""
    if not isinstance(projects, list): raise ValueError("projects must be a list")
    currencies, resources, seen = defaultdict(lambda: {"budget": Decimal(0), "actual": Decimal(0), "forecast": Decimal(0)}), {}, set()
    output = []
    for p in projects:
        pid, currency = str(p.get("project_id") or "").strip(), str(p.get("currency") or "").upper().strip()
        if not pid or pid in seen or not currency: raise ValueError("Each project requires unique project_id and currency")
        seen.add(pid)
        budget = _number(p.get("approved_budget", 0), f"{pid}.approved_budget")
        actual = _number(p.get("actual_cost", 0), f"{pid}.actual_cost")
        forecast = _number(p.get("forecast_cost", actual), f"{pid}.forecast_cost")
        currencies[currency]["budget"] += budget; currencies[currency]["actual"] += actual; currencies[currency]["forecast"] += forecast
        project_resources = []
        for r in p.get("resources", []):
            rid = str(r.get("resource_id") or "").strip()
            if not rid: raise ValueError("resource_id is required for resource position")
            demand = _number(r.get("demand_hours", 0), f"{rid}.demand_hours")
            capacity = _number(r.get("capacity_hours", 0), f"{rid}.capacity_hours")
            if rid not in resources:
                resources[rid] = {"demand_hours": Decimal(0), "capacity_hours": capacity}
            elif resources[rid]["capacity_hours"] != capacity:
                raise ValueError(f"Conflicting capacity snapshots for resource {rid}; provide one common reporting-period capacity")
            resources[rid]["demand_hours"] += demand
            project_resources.append({"resource_id": rid, "demand_hours": float(demand), "capacity_hours": float(capacity),
                                      "overload_hours": float(max(demand-capacity, Decimal(0)))})
        output.append({"project_id": pid, "currency": currency, "approved_budget": float(budget),
                       "actual_cost": float(actual), "forecast_cost": float(forecast),
                       "forecast_variance": float(budget-forecast), "resources": project_resources})
    return {"projects": output,
            "currency_totals": {c: {k: float(v) for k,v in vals.items()} for c,vals in sorted(currencies.items())},
            "resource_totals": {rid: {"demand_hours": float(v["demand_hours"]), "capacity_hours": float(v["capacity_hours"]),
                "overload_hours": float(max(v["demand_hours"]-v["capacity_hours"], Decimal(0)))} for rid,v in sorted(resources.items())},
            "currency_policy": "No implicit currency conversion", "source_policy": "Read-only authorised programme/project projections"}


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered: return None
    index = (len(ordered)-1) * percentile
    low, high = int(index), min(int(index)+1, len(ordered)-1)
    fraction = index-low
    return round(ordered[low] * (1-fraction) + ordered[high] * fraction, 3)


def simulate_programme_risk(activities, risks, *, iterations=1000, seed=17, project_start=None,
                            working_weekdays=(0,1,2,3,4), holidays=(), base_cost=0):
    """Monte Carlo schedule/cost exposure using triangular duration and risk impacts.

    Every risk has probability [0,1], min/max/most_likely_days and optional
    min/max/most_likely_cost. The simulation is reproducible for a fixed seed.
    """
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not 100 <= iterations <= 10000:
        raise ValueError("iterations must be an integer between 100 and 10000")
    if not isinstance(seed, int) or isinstance(seed, bool): raise ValueError("seed must be an integer")
    if not isinstance(risks, list): raise ValueError("risks must be a list")
    risk_rows, ids = [], set()
    for r in risks:
        rid = str(r.get("risk_id") or "").strip()
        if not rid or rid in ids: raise ValueError("Risk IDs must be present and unique")
        ids.add(rid)
        probability = _number(r.get("probability"), f"{rid}.probability")
        if probability > 1: raise ValueError("risk probability must not exceed 1")
        days = [_number(r.get(k, 0), f"{rid}.{k}") for k in ("min_days", "most_likely_days", "max_days")]
        costs = [_number(r.get(k, 0), f"{rid}.{k}") for k in ("min_cost", "most_likely_cost", "max_cost")]
        if not days[0] <= days[1] <= days[2] or not costs[0] <= costs[1] <= costs[2]:
            raise ValueError("Risk triangular parameters must satisfy min <= most_likely <= max")
        risk_rows.append((float(probability), tuple(map(float, days)), tuple(map(float, costs))))
    base = _number(base_cost, "base_cost")
    rng = random.Random(seed); durations, costs = [], []
    for _ in range(iterations):
        sampled = []
        for a in activities:
            optimistic = a.get("optimistic_duration", a.get("duration"))
            likely = a.get("most_likely_duration", a.get("duration"))
            pessimistic = a.get("pessimistic_duration", a.get("duration"))
            lo, mode, hi = map(float, (_number(optimistic, "optimistic_duration", 1),
                                      _number(likely, "most_likely_duration", 1),
                                      _number(pessimistic, "pessimistic_duration", 1)))
            if not lo <= mode <= hi: raise ValueError("Activity duration parameters must satisfy optimistic <= most_likely <= pessimistic")
            sampled.append({**a, "duration": max(1, round(rng.triangular(lo, hi, mode)))})
        cpm = calculate_cpm(sampled)
        risk_days, risk_cost = 0.0, 0.0
        for probability, d, c in risk_rows:
            if rng.random() < probability:
                risk_days += rng.triangular(d[0], d[2], d[1])
                risk_cost += rng.triangular(c[0], c[2], c[1])
        durations.append(float(cpm["duration"]) + risk_days)
        costs.append(float(base) + risk_cost)
    result = {"iterations": iterations, "seed": seed,
        "schedule_days": {"p50": _percentile(durations,.50), "p80": _percentile(durations,.80), "p90": _percentile(durations,.90), "mean": round(sum(durations)/iterations,3)},
        "cost": {"p50": _percentile(costs,.50), "p80": _percentile(costs,.80), "p90": _percentile(costs,.90), "mean": round(sum(costs)/iterations,3)},
        "risk_count": len(risk_rows), "method": "Monte Carlo; triangular activity and risk-impact distributions",
        "limitations": "Risk impacts are additive and independent; correlations, mitigation effectiveness and calendar-day conversion are not inferred."}
    if project_start:
        result["project_start"] = date.fromisoformat(str(project_start)).isoformat()
        result["calendar_note"] = "Simulation outputs are working-day offsets; dated percentile finish dates are not inferred."
    return result


def compare_portfolio_scenarios(scenarios):
    """Compare supplied, independently calculated scenario snapshots without FX."""
    if not isinstance(scenarios, list) or not scenarios: raise ValueError("At least one scenario is required")
    names, rows = set(), []
    for s in scenarios:
        name = str(s.get("scenario_id") or "").strip()
        if not name or name in names: raise ValueError("Scenario IDs must be present and unique")
        names.add(name)
        cost = _number(s.get("forecast_cost", 0), f"{name}.forecast_cost")
        duration = _number(s.get("forecast_duration_days", 0), f"{name}.forecast_duration_days")
        benefit = _number(s.get("benefit_score", 0), f"{name}.benefit_score")
        exposure = _number(s.get("risk_exposure", 0), f"{name}.risk_exposure")
        rows.append({"scenario_id": name, "currency": str(s.get("currency") or "").upper(),
                     "forecast_cost": float(cost), "forecast_duration_days": float(duration),
                     "benefit_score": float(benefit), "risk_exposure": float(exposure)})
    if any(not row["currency"] for row in rows): raise ValueError("Each scenario requires a currency")
    rows.sort(key=lambda x: (x["currency"], x["risk_exposure"], x["forecast_duration_days"], x["forecast_cost"], -x["benefit_score"], x["scenario_id"]))
    current_currency, rank = None, 0
    for row in rows:
        if row["currency"] != current_currency: current_currency, rank = row["currency"], 0
        rank += 1; row["rank_within_currency"] = rank
    return {"scenarios": rows, "ranking_policy": "Ranked only within the same currency: lowest risk exposure, then shortest duration, then lowest cost, then highest benefit.",
            "decision_status": "Advisory comparison only; no scenario is approved or applied."}


def build_intervention_submission(exception_id, action, actor_id):
    """Create a validated host-workflow command envelope; never persist locally."""
    exception_id, actor_id = str(exception_id or "").strip(), str(actor_id or "").strip()
    if not exception_id or not actor_id: raise ValueError("exception_id and authenticated actor are required")
    if not isinstance(action, dict): raise ValueError("action must be an object")
    title, owner, due = (str(action.get(k) or "").strip() for k in ("title", "owner", "due_date"))
    if not title or not owner: raise ValueError("Corrective action title and owner are required")
    try: due = date.fromisoformat(due).isoformat() if due else ""
    except ValueError: raise ValueError("due_date must be ISO YYYY-MM-DD")
    return {"doctype": "Project Corrective Action", "exception_id": exception_id,
            "title": title, "owner": owner, "due_date": due, "requested_by": actor_id,
            "project": str(action.get("project") or "").strip(),
            "workflow_action": "submit_for_approval", "status": "Draft",
            "persistence_policy": "Host workflow adapter must validate, authorise and persist atomically; ProjectOne does not persist this envelope."}
