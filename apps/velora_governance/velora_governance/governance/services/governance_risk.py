"""Configurable governance risk scoring and risk summaries."""

def score_governance_risk(factors, *, weights=None, thresholds=None):
    """Score normalized 0-100 risk factors; weights are configurable.

    Factors are mappings {name, value, weight?}. Default weights are equal.
    Values outside 0..100 are rejected to prevent silent mis-scaling.
    """
    factors = list(factors or [])
    cfg_weights = weights or {}
    scored = []
    total_weight = 0.0
    weighted = 0.0
    for factor in factors:
        value = float(factor.get("value", 0))
        if not 0 <= value <= 100: raise ValueError(f"Risk factor '{factor.get('name')}' must be between 0 and 100")
        weight = float(factor.get("weight", cfg_weights.get(factor.get("name"), 1)))
        if weight < 0: raise ValueError("Risk weights cannot be negative")
        scored.append({"name": factor.get("name"), "value": value, "weight": weight, "weighted_score": value * weight})
        weighted += value * weight; total_weight += weight
    score = round(weighted / total_weight, 2) if total_weight else 0.0
    t = {"Low": 25, "Moderate": 50, "High": 75, "Critical": 100, **(thresholds or {})}
    level = "Low" if score < float(t["Moderate"]) else "Moderate" if score < float(t["High"]) else "High" if score < float(t["Critical"]) else "Critical"
    return {"risk_score": score, "risk_level": level, "factor_count": len(scored), "factors": scored}


def summarize_risk_register(records):
    rows = list(records or [])
    levels = {"Critical": 0, "High": 0, "Moderate": 0, "Low": 0, "Unrated": 0}
    for r in rows: levels[r.get("risk_level") if r.get("risk_level") in levels else "Unrated"] += 1
    return {"total_risks": len(rows), "risk_level_counts": levels,
        "open_risks": sum(r.get("status", "Open") not in ("Closed", "Resolved", "Accepted") for r in rows),
        "high_priority_risks": levels["Critical"] + levels["High"]}
