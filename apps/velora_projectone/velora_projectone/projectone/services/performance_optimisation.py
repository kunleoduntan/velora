"""Advanced project performance, forecasting and portfolio optimisation.

Pure, deterministic calculations. Inputs must be sourced and authorised by the
host application; this module does not persist transactions or alter baselines.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
from collections import defaultdict


def _d(value, field, *, minimum=None):
    try: x = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError): raise ValueError(f"{field} must be numeric.")
    if not x.is_finite(): raise ValueError(f"{field} must be finite.")
    if minimum is not None and x < minimum: raise ValueError(f"{field} cannot be below {minimum}.")
    return x


def _f(x): return float(x) if x is not None else None


def forecast_earned_value(*, pv, ev, ac, bac, method="cpi", remaining_work=None,
                          planned_duration_days=None, elapsed_duration_days=None):
    """EVM metrics plus selectable EAC methods and TCPI.

    Methods: cpi, spi_cpi, bottom_up. No forecast is fabricated when its
    denominator is zero or bottom-up remaining work is absent.
    """
    pv, ev, ac, bac = (_d(v, n, minimum=0) for v, n in ((pv,"pv"),(ev,"ev"),(ac,"ac"),(bac,"bac")))
    if ev > bac and bac > 0: earned_over_bac = True
    else: earned_over_bac = False
    cpi = ev/ac if ac else None
    spi = ev/pv if pv else None
    if method not in {"cpi", "spi_cpi", "bottom_up"}: raise ValueError("Unsupported EAC method.")
    if method == "cpi": eac = bac/cpi if cpi and cpi > 0 else None
    elif method == "spi_cpi":
        factor = cpi*spi if cpi is not None and spi is not None else None
        eac = bac/factor if factor and factor > 0 else None
    else:
        if remaining_work is None: raise ValueError("remaining_work is required for bottom_up forecasting.")
        eac = ac + _d(remaining_work, "remaining_work", minimum=0)
    etc = eac-ac if eac is not None else None
    vac = bac-eac if eac is not None else None
    tcpi_den = bac-ac
    tcpi = (bac-ev)/tcpi_den if tcpi_den > 0 else None
    duration_forecast = None
    if planned_duration_days is not None or elapsed_duration_days is not None:
        planned = _d(planned_duration_days, "planned_duration_days", minimum=0)
        elapsed = _d(elapsed_duration_days, "elapsed_duration_days", minimum=0)
        duration_forecast = (elapsed + max(planned-elapsed, Decimal(0))/spi) if spi and spi > 0 else None
    return {"pv":_f(pv),"ev":_f(ev),"ac":_f(ac),"bac":_f(bac),"sv":_f(ev-pv),"cv":_f(ev-ac),
            "spi":_f(spi),"cpi":_f(cpi),"eac_method":method,"eac":_f(eac),"etc":_f(etc),
            "vac":_f(vac),"tcpi":_f(tcpi),"duration_forecast_days":_f(duration_forecast),
            "earned_value_exceeds_budget_at_completion":earned_over_bac}


def analyse_schedule_trend(observations):
    """Analyse chronological schedule variance and simple least-squares trend."""
    if not isinstance(observations, list) or len(observations) < 2:
        raise ValueError("At least two schedule observations are required.")
    rows=[]
    for row in observations:
        period=str(row.get("period", "")).strip()
        if not period: raise ValueError("Each observation requires a period.")
        rows.append((period,_d(row.get("variance_days"),"variance_days")))
    if len({p for p,_ in rows}) != len(rows): raise ValueError("Schedule observation periods must be unique.")
    rows.sort(key=lambda x:x[0]); n=Decimal(len(rows)); xs=list(map(Decimal,range(len(rows)))); ys=[v for _,v in rows]
    xbar=sum(xs)/n; ybar=sum(ys)/n
    denom=sum((x-xbar)**2 for x in xs)
    slope=sum((x-xbar)*(y-ybar) for x,y in zip(xs,ys))/denom if denom else Decimal(0)
    intercept=ybar-slope*xbar
    forecast=intercept+slope*Decimal(len(rows))
    direction="Improving" if slope < 0 else ("Deteriorating" if slope > 0 else "Stable")
    return {"observations":[{"period":p,"variance_days":_f(v)} for p,v in rows],
            "variance_slope_days_per_period":_f(slope),"trend":direction,
            "next_period_forecast_variance_days":_f(forecast),
            "forecast_method":"ordinary least-squares linear trend; directional indicator only"}


def optimise_resource_conflicts(activities, capacities):
    """Priority-first, period-bucket resource assignment; no date mutation.

    Each activity must name resource_id, period, hours and priority. This is a
    transparent greedy heuristic, not a mathematically optimal RCPSP solver.
    """
    remaining={}
    for row in capacities:
        key=(str(row.get("resource_id")),str(row.get("period")))
        if key in remaining: raise ValueError("Duplicate resource-period capacity.")
        remaining[key]=_d(row.get("available_hours"),"available_hours",minimum=0)
    seen=set(); out=[]
    ordered=sorted(activities,key=lambda a:(int(a.get("priority",999)),str(a.get("planned_start","")),str(a.get("activity_id",""))))
    for a in ordered:
        aid=str(a.get("activity_id", "")); rid=str(a.get("resource_id", "")); period=str(a.get("period", ""))
        if not aid or not rid or not period: raise ValueError("Each activity requires activity_id, resource_id and period.")
        if aid in seen: raise ValueError("Activity IDs must be unique.")
        seen.add(aid); hours=_d(a.get("hours"),"hours",minimum=0); key=(rid,period)
        available=remaining.get(key,Decimal(0)); assigned=min(hours,available); remaining[key]=available-assigned
        out.append({"activity_id":aid,"resource_id":rid,"period":period,"priority":int(a.get("priority",999)),
                    "requested_hours":_f(hours),"assigned_hours":_f(assigned),"unassigned_hours":_f(hours-assigned),
                    "status":"Fully Allocated" if assigned==hours else ("Partially Allocated" if assigned else "Unallocated")})
    return {"allocations":out,"unassigned_hours":_f(sum((_d(x["unassigned_hours"],"unassigned_hours") for x in out),Decimal(0))),
            "remaining_capacity":[{"resource_id":k[0],"period":k[1],"available_hours":_f(v)} for k,v in sorted(remaining.items())],
            "method":"priority, planned start, activity ID; greedy heuristic; no schedule-date mutation"}


def portfolio_profitability_trend(observations):
    """Aggregate project contribution margin by period and currency, without FX."""
    totals=defaultdict(lambda:{"revenue":Decimal(0),"cost":Decimal(0)})
    for r in observations:
        period=str(r.get("period", "")).strip(); currency=str(r.get("currency", "")).strip().upper()
        if not period or not currency: raise ValueError("Each profitability row requires period and currency.")
        revenue=_d(r.get("revenue"),"revenue",minimum=0); cost=_d(r.get("cost"),"cost",minimum=0)
        totals[(period,currency)]["revenue"]+=revenue; totals[(period,currency)]["cost"]+=cost
    result=[]
    for (period,currency),v in sorted(totals.items()):
        margin=v["revenue"]-v["cost"]
        result.append({"period":period,"currency":currency,"revenue":_f(v["revenue"]),"cost":_f(v["cost"]),
                       "contribution_margin":_f(margin),"margin_percent":_f(margin/v["revenue"]*100) if v["revenue"] else None})
    return {"periods":result,"currency_policy":"No cross-currency aggregation or implicit FX conversion."}


def schedule_benefit_reviews(benefits, as_of_period):
    """Build benefit review status from explicit review periods and measurements."""
    output=[]
    for b in benefits:
        bid=str(b.get("benefit_id", "")).strip()
        if not bid: raise ValueError("Each benefit requires benefit_id.")
        due=str(b.get("next_review_period", "")).strip()
        if not due: raise ValueError("Each benefit requires next_review_period.")
        baseline=_d(b.get("baseline_value",0),"baseline_value")
        target=_d(b.get("target_value"),"target_value")
        actual=None if b.get("actual_value") is None else _d(b.get("actual_value"),"actual_value")
        status="Measurement Missing" if actual is None else ("Target Achieved" if ((target>=baseline and actual>=target) or (target<baseline and actual<=target)) else "In Progress")
        overdue=due < str(as_of_period)
        output.append({"benefit_id":bid,"owner":b.get("owner"),"next_review_period":due,"status":"Overdue" if overdue else status,
                       "measurement_missing":actual is None,"overdue":overdue,"actual_value":_f(actual)})
    return {"reviews":output,"overdue_count":sum(1 for x in output if x["overdue"]),
            "missing_measurement_count":sum(1 for x in output if x["measurement_missing"])}


def build_management_alerts(exceptions, *, owners=None):
    """Attach accountable owners to exception alerts; unassigned remains explicit."""
    owners=owners or {}; alerts=[]
    for e in exceptions:
        eid=str(e.get("exception_id", "")).strip()
        if not eid: raise ValueError("Each exception requires exception_id.")
        owner=owners.get(eid) or e.get("owner")
        severity=e.get("severity","Medium")
        if severity not in {"Low","Medium","High","Critical"}: raise ValueError("Unsupported alert severity.")
        alerts.append({"exception_id":eid,"project_id":e.get("project_id"),"severity":severity,
                       "owner":owner,"ownership_status":"Assigned" if owner else "Unassigned",
                       "description":str(e.get("description", "")),"due_period":e.get("due_period")})
    order={"Critical":0,"High":1,"Medium":2,"Low":3}
    alerts.sort(key=lambda x:(order[x["severity"]],x["due_period"] or "",x["exception_id"]))
    return {"alerts":alerts,"count":len(alerts),"unassigned_count":sum(1 for x in alerts if not x["owner"])}
