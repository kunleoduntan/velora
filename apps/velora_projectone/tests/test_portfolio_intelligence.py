import pytest
from velora_projectone.projectone.services.portfolio_intelligence import (
    prioritise_portfolio, model_portfolio_scenario, analyse_cross_project_dependencies,
    forecast_enterprise_capacity, build_portfolio_exception_register,
)


def test_prioritisation_normalises_weights_and_ranks_deterministically():
    result = prioritise_portfolio([
        {"project_id": "P2", "strategic_alignment": 50, "business_value": 50},
        {"project_id": "P1", "strategic_alignment": 100, "business_value": 100},
    ])
    assert result["projects"][0]["project_id"] == "P1"
    assert result["projects"][0]["rank"] == 1
    assert sum(result["weights"].values()) == pytest.approx(100)


def test_prioritisation_rejects_bad_dimension_and_duplicate():
    with pytest.raises(ValueError): prioritise_portfolio([{"project_id": "P", "readiness": 101}])
    with pytest.raises(ValueError): prioritise_portfolio([{"project_id": "P"}, {"project_id": "P"}])


def test_scenario_separates_currency_and_does_not_mutate_input():
    rows = [{"project_id": "A", "currency": "NGN", "approved_budget": 100, "expected_benefit": 20, "forecast_exposure": 90},
            {"project_id": "B", "currency": "USD", "approved_budget": 50, "expected_benefit": 10, "forecast_exposure": 40}]
    result = model_portfolio_scenario(rows, actions={"A": "cancel"}, contingency_percent=10)
    assert result["currency_totals"]["NGN"]["scenario_budget"] == 0
    assert result["currency_totals"]["USD"]["scenario_budget"] == 50
    assert rows[0]["approved_budget"] == 100


def test_scenario_rejects_unknown_action():
    with pytest.raises(ValueError): model_portfolio_scenario([{"project_id": "A"}], actions={"A": "delete"})


def test_cross_project_dependency_detects_cycle():
    ok = analyse_cross_project_dependencies([{"predecessor_project": "A", "successor_project": "B"},
                                             {"predecessor_project": "B", "successor_project": "C"}])
    assert ok["valid"] and ok["topological_order"] == ["A", "B", "C"]
    bad = analyse_cross_project_dependencies([{"predecessor_project": "A", "successor_project": "B"},
                                               {"predecessor_project": "B", "successor_project": "A"}])
    assert not bad["valid"] and set(bad["cycle_involved_projects"]) == {"A", "B"}


def test_capacity_forecast_flags_overallocation_and_missing_capacity():
    result = forecast_enterprise_capacity(
        [{"resource_id": "R1", "period": "2026-12", "project_id": "P1", "demand_hours": 90},
         {"resource_id": "R2", "period": "2026-12", "project_id": "P2", "demand_hours": 5}],
        [{"resource_id": "R1", "period": "2026-12", "available_hours": 80}])
    assert result["over_allocated_periods"] == 1
    assert result["capacity_missing_periods"] == 1


def test_exception_register_is_explainable_and_severity_ranked():
    result = build_portfolio_exception_register([
        {"project_id": "P1", "schedule_variance_days": 30, "approved_budget": 100, "forecast_exposure": 140, "critical_risk_open": True},
        {"project_id": "P2", "schedule_variance_days": 0, "approved_budget": 100, "forecast_exposure": 100},
    ])
    assert result["high_count"] == 3
    assert result["exceptions"][0]["severity"] == "High"
    assert result["count"] == 3


def test_defer_removes_project_from_active_horizon_but_preserves_deferred_values():
    result = model_portfolio_scenario(
        [{"project_id": "A", "currency": "NGN", "approved_budget": 100,
          "expected_benefit": 150, "forecast_exposure": 90}],
        actions={"A": "defer"})
    totals = result["currency_totals"]["NGN"]
    assert totals["scenario_budget"] == 0
    assert totals["deferred_budget"] == 100
    assert totals["deferred_benefit"] == 150
