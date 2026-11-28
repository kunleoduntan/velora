"""Enterprise delivery forecasting, programme CPM and intervention controls.

Pure deterministic read models. Callers must supply authorised, tenant-scoped
source rows. These functions never persist records or create ledger entries.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation


def _num(value, field, minimum=None):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric.")
    if not result.is_finite() or (minimum is not None and result < Decimal(str(minimum))):
        raise ValueError(f"{field} is outside the permitted range.")
    return result


def _float(value):
    return None if value is None else float(value)


def forecast_portfolio_delivery(projects):
    """Calculate per-project EAC, schedule forecast and a transparent health index.

    The health index is a management indicator, not a statistical probability.
    Financial totals are separated by currency; no FX is inferred.
    """
    if not isinstance(projects, list):
        raise ValueError("projects must be a list.")
    seen, rows, totals = set(), [], defaultdict(lambda: {k: Decimal(0) for k in
        ("approved_budget", "actual_cost", "forecast_eac", "forecast_variance")})
    for p in projects:
        pid = str(p.get("project_id") or "").strip()
        currency = str(p.get("currency") or "").strip().upper()
        if not pid or pid in seen or not currency:
            raise ValueError("Each project requires a unique project_id and currency.")
        seen.add(pid)
        bac = _num(p.get("approved_budget"), f"{pid}.approved_budget", 0)
        ac = _num(p.get("actual_cost"), f"{pid}.actual_cost", 0)
        ev = _num(p.get("earned_value"), f"{pid}.earned_value", 0)
        pv = _num(p.get("planned_value"), f"{pid}.planned_value", 0)
        if ev > bac and bac > 0:
            raise ValueError(f"{pid}.earned_value cannot exceed approved_budget for this forecast.")
        cpi = ev / ac if ac else None
        spi = ev / pv if pv else None
        eac = (bac / cpi) if cpi and cpi > 0 else None
        vac = bac - eac if eac is not None else None
        planned_days = _num(p.get("planned_duration_days", 0), f"{pid}.planned_duration_days", 0)
        elapsed_days = _num(p.get("elapsed_duration_days", 0), f"{pid}.elapsed_duration_days", 0)
        duration = elapsed_days + max(planned_days - elapsed_days, Decimal(0)) / spi if spi and spi > 0 else None
        # 50 points each for CPI and SPI, capped at plan performance.
        index = None if cpi is None or spi is None else min(Decimal(100),
            (min(cpi, Decimal(1)) + min(spi, Decimal(1))) * Decimal(50))
        band = "Not Rated" if index is None else ("On Track" if index >= 90 else ("Watch" if index >= 75 else "Intervention Required"))
        rows.append({"project_id": pid, "currency": currency, "approved_budget": float(bac),
            "actual_cost": float(ac), "eac": _float(eac), "forecast_variance": _float(vac),
            "cpi": _float(cpi), "spi": _float(spi), "forecast_duration_days": _float(duration),
            "delivery_health_index": _float(index), "delivery_health_band": band,
            "index_definition": "50% capped CPI + 50% capped SPI; indicator, not probability"})
        totals[currency]["approved_budget"] += bac
        totals[currency]["actual_cost"] += ac
        if eac is not None:
            totals[currency]["forecast_eac"] += eac
            totals[currency]["forecast_variance"] += bac - eac
    return {"projects": rows, "currency_totals": {c: {k: float(v) for k, v in vals.items()}
            for c, vals in sorted(totals.items())},
            "currency_policy": "Separate currency totals; no implicit FX conversion.",
            "source_policy": "Caller-authorised read-only source rows; no accounting writes."}


def analyse_programme_critical_path(milestones, dependencies):
    """Calculate CPM over programme milestones using duration and dependency lag.

    Milestones are modelled as activities with duration_days. Dependencies are
    finish-to-start links. Dates are relative offsets, not calendar dates.
    """
    if not isinstance(milestones, list) or not isinstance(dependencies, list):
        raise ValueError("milestones and dependencies must be lists.")
    nodes, by_id = [], {}
    for m in milestones:
        mid = str(m.get("milestone_id") or "").strip()
        if not mid or mid in by_id:
            raise ValueError("Milestones require unique milestone_id values.")
        duration = _num(m.get("duration_days", 0), f"{mid}.duration_days", 0)
        if duration != duration.to_integral_value():
            raise ValueError("Milestone duration_days must be whole days.")
        by_id[mid] = {"milestone_id": mid, "project_id": str(m.get("project_id") or ""),
                      "name": m.get("name", mid), "duration": int(duration)}
        nodes.append(mid)
    edges, seen = defaultdict(list), set()
    indegree = {n: 0 for n in nodes}
    for d in dependencies:
        pred, succ = str(d.get("predecessor_id") or ""), str(d.get("successor_id") or "")
        if pred not in by_id or succ not in by_id or pred == succ:
            raise ValueError("Each dependency must link two distinct supplied milestones.")
        if (pred, succ) in seen:
            raise ValueError("Duplicate milestone dependency.")
        lag = _num(d.get("lag_days", 0), "lag_days")
        if lag != lag.to_integral_value():
            raise ValueError("lag_days must be a whole number.")
        seen.add((pred, succ)); edges[pred].append((succ, int(lag))); indegree[succ] += 1
    ready = sorted(n for n, deg in indegree.items() if deg == 0)
    order = []
    while ready:
        node = ready.pop(0); order.append(node)
        for nxt, _ in sorted(edges[node]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt); ready.sort()
    if len(order) != len(nodes):
        cyclic = sorted(n for n, deg in indegree.items() if deg > 0)
        raise ValueError("Programme milestone dependency cycle detected: " + ", ".join(cyclic))
    early_start, early_finish = {}, {}
    for node in order:
        start = max((early_finish[p] + lag for p in nodes for child, lag in edges[p] if child == node), default=0)
        early_start[node] = start; early_finish[node] = start + by_id[node]["duration"]
    project_duration = max(early_finish.values(), default=0)
    late_finish, late_start = {}, {}
    for node in reversed(order):
        successors = [late_start[nxt] - lag for nxt, lag in edges[node]]
        finish = min(successors) if successors else project_duration
        late_finish[node] = finish; late_start[node] = finish - by_id[node]["duration"]
    rows = []
    for node in order:
        m = by_id[node]; slack = late_start[node] - early_start[node]
        rows.append({"milestone_id": node, "project_id": m["project_id"], "name": m["name"],
            "duration_days": m["duration"], "early_start_day": early_start[node],
            "early_finish_day": early_finish[node], "late_start_day": late_start[node],
            "late_finish_day": late_finish[node], "total_float_days": slack,
            "critical": slack == 0})
    return {"milestones": rows, "programme_duration_days": project_duration,
            "critical_path": [r["milestone_id"] for r in rows if r["critical"]],
            "dependency_count": len(seen), "relationship": "finish-to-start with signed whole-day lag",
            "date_basis": "relative working-day offsets; no calendar dates inferred"}


def build_intervention_centre(exceptions, actions=None, *, as_of_period=None):
    """Join exception rows to proposed corrective actions and prioritise follow-up.

    Action rows are read-model proposals only; lifecycle changes require the
    host workflow and persistence services.
    """
    if not isinstance(exceptions, list) or (actions is not None and not isinstance(actions, list)):
        raise ValueError("exceptions and actions must be lists.")
    action_by_exception = {}
    for a in actions or []:
        eid = str(a.get("exception_id") or "").strip()
        if not eid or eid in action_by_exception:
            raise ValueError("Each corrective action requires a unique exception_id.")
        status = a.get("status", "Open")
        if status not in {"Open", "In Progress", "Resolved", "Cancelled"}:
            raise ValueError("Unsupported corrective action status.")
        action_by_exception[eid] = a
    severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    output, seen = [], set()
    for e in exceptions:
        eid = str(e.get("exception_id") or "").strip()
        if not eid or eid in seen:
            raise ValueError("Exceptions require unique exception_id values.")
        seen.add(eid)
        severity = e.get("severity", "Medium")
        if severity not in severity_order:
            raise ValueError("Unsupported exception severity.")
        action = action_by_exception.get(eid)
        due = (action or {}).get("due_period") or e.get("due_period")
        status = (action or {}).get("status", "Open")
        overdue = bool(as_of_period and due and str(due) < str(as_of_period) and status not in {"Resolved", "Cancelled"})
        output.append({"exception_id": eid, "project_id": e.get("project_id"), "title": e.get("title", e.get("description", eid)),
            "severity": severity, "owner": (action or {}).get("owner") or e.get("owner"),
            "action": (action or {}).get("action"), "action_status": status,
            "due_period": due, "overdue": overdue,
            "intervention_status": "Action Required" if not action else ("Overdue" if overdue else status),
            "action_record_present": action is not None})
    output.sort(key=lambda r: (severity_order[r["severity"]], not r["overdue"], str(r["due_period"] or "9999"), r["exception_id"]))
    return {"interventions": output, "count": len(output),
        "critical_count": sum(r["severity"] == "Critical" for r in output),
        "overdue_count": sum(r["overdue"] for r in output),
        "without_action_count": sum(not r["action_record_present"] for r in output),
        "persistence": "read-only projection; corrective actions must be submitted through host workflow"}
