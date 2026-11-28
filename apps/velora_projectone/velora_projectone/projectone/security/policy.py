"""Framework-neutral row-scope policy primitives.

The host Velora API must supply authenticated principal, company membership and
project role assignments. This module never grants access based on client input.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class ProjectPrincipal:
    user_id: str
    companies: frozenset
    project_roles: dict
    system_roles: frozenset = frozenset()


def assert_company_access(principal, company):
    if "System Manager" in principal.system_roles:
        return True
    if company not in principal.companies:
        raise PermissionError("You do not have access to this company.")
    return True


def assert_project_access(principal, project_id, company, allowed_roles=None):
    assert_company_access(principal, company)
    if "System Manager" in principal.system_roles:
        return True
    role = principal.project_roles.get(project_id)
    if not role:
        raise PermissionError("You are not a member of this project.")
    if allowed_roles and role not in set(allowed_roles):
        raise PermissionError("Your project role does not permit this operation.")
    return True


def redact_financial_fields(record, can_view_financials):
    if can_view_financials:
        return dict(record)
    hidden = {
        "approved_budget", "original_budget", "approved_budget_changes", "pending_budget_changes",
        "actual_cost", "open_commitments", "available_budget", "total_exposure",
        "estimate_to_complete", "estimate_at_completion", "forecast_variance", "forecast_overrun",
        "recognised_revenue", "forecast_revenue", "project_revenue", "profit_margin",
        "forecast_margin", "forecast_project_margin", "recognised_profit", "cost_rate", "billing_rate",
        "transaction_price", "allocated_transaction_price", "cumulative_actual_cost", "forecast_total_cost",
        "prior_cumulative_revenue", "cumulative_revenue", "current_period_revenue", "cumulative_cost",
        "current_period_cost", "cumulative_profit", "current_period_profit", "forecast_total_profit",
        "forecast_margin_percent", "potential_onerous_contract_loss", "planned_value", "earned_value",
        "cost_variance", "schedule_variance", "cost_performance_index", "schedule_performance_index",
        "budget_at_completion", "estimate_at_completion", "variance_at_completion",
    }
    return {k: v for k, v in record.items() if k not in hidden}
