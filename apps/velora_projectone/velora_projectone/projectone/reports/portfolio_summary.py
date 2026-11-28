"""Deterministic portfolio summary over permission-filtered project rows."""
from decimal import Decimal


def build_portfolio_summary(projects):
    if not isinstance(projects, list): raise ValueError("projects must be a list.")
    statuses, total_budget, actual_cost, commitments = {}, Decimal("0"), Decimal("0"), Decimal("0")
    for row in projects:
        status = str(row.get("status") or "Unknown")
        statuses[status] = statuses.get(status, 0) + 1
        total_budget += Decimal(str(row.get("approved_budget", 0)))
        actual_cost += Decimal(str(row.get("actual_cost", 0)))
        commitments += Decimal(str(row.get("open_commitments", 0)))
    exposure = actual_cost + commitments
    return {"project_count": len(projects), "status_counts": statuses,
            "approved_budget": total_budget, "actual_cost": actual_cost,
            "open_commitments": commitments, "total_exposure": exposure,
            "available_budget": total_budget-exposure}
