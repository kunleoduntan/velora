import pytest
from velora_projectone.projectone.services.programme_intelligence import (
    programme_calendar_schedule, programme_cost_resource_position,
    simulate_programme_risk, compare_portfolio_scenarios, build_intervention_submission,
)


def test_calendar_programme_cpm_supports_relationships_and_holidays():
    result = programme_calendar_schedule([
        {"id":"A", "duration":2},
        {"id":"B", "duration":3, "dependencies":[{"predecessor":"A", "type":"SS", "lag":1}]},
        {"id":"C", "duration":1, "dependencies":[{"predecessor":"B", "type":"FF", "lag":0}]},
    ], "2026-12-21", holidays=["2026-12-25"])
    rows = {r["id"]: r for r in result["activities"]}
    assert rows["A"]["early_start_date"] == "2026-12-21"
    assert rows["B"]["early_start_date"] == "2026-12-22"
    assert result["date_basis"].startswith("working calendar")
    assert result["dependency_types"] == ["FS", "SS", "FF", "SF"]


def test_calendar_programme_rejects_bad_calendar_and_dependency_cycle():
    with pytest.raises(ValueError): programme_calendar_schedule([], "2026-01-01", working_weekdays=[])
    with pytest.raises(ValueError, match="cycle"):
        programme_calendar_schedule([
            {"id":"A", "duration":1, "dependencies":[{"predecessor":"B"}]},
            {"id":"B", "duration":1, "dependencies":[{"predecessor":"A"}]},
        ], "2026-01-01")


def test_cost_resource_position_separates_currency_and_aggregates_capacity():
    result = programme_cost_resource_position([
        {"project_id":"P1", "currency":"NGN", "approved_budget":100, "actual_cost":40, "forecast_cost":90,
         "resources":[{"resource_id":"R1", "demand_hours":12, "capacity_hours":8}]},
        {"project_id":"P2", "currency":"NGN", "approved_budget":50, "actual_cost":10, "forecast_cost":45,
         "resources":[{"resource_id":"R1", "demand_hours":10, "capacity_hours":8}]},
        {"project_id":"P3", "currency":"USD", "approved_budget":10, "resources":[]},
    ])
    assert result["currency_totals"]["NGN"]["budget"] == 150
    assert result["resource_totals"]["R1"]["overload_hours"] == 14
    assert set(result["currency_totals"]) == {"NGN", "USD"}


def test_monte_carlo_is_reproducible_and_returns_percentiles():
    activities = [{"id":"A", "duration":5, "optimistic_duration":3,
                   "most_likely_duration":5, "pessimistic_duration":8}]
    risks = [{"risk_id":"R1", "probability":0.5, "min_days":1, "most_likely_days":3,
              "max_days":6, "min_cost":10, "most_likely_cost":20, "max_cost":40}]
    a = simulate_programme_risk(activities, risks, iterations=300, seed=42, base_cost=100)
    b = simulate_programme_risk(activities, risks, iterations=300, seed=42, base_cost=100)
    assert a == b
    assert a["schedule_days"]["p90"] >= a["schedule_days"]["p50"]
    assert a["cost"]["p80"] >= 100


def test_monte_carlo_rejects_invalid_distribution_and_iteration_count():
    with pytest.raises(ValueError): simulate_programme_risk([], [], iterations=20)
    with pytest.raises(ValueError): simulate_programme_risk([], [{"risk_id":"R", "probability":1.2}])


def test_scenario_comparison_is_advisory_and_deterministically_ranked():
    result = compare_portfolio_scenarios([
        {"scenario_id":"B", "currency":"NGN", "forecast_cost":100, "forecast_duration_days":20, "benefit_score":8, "risk_exposure":5},
        {"scenario_id":"A", "currency":"NGN", "forecast_cost":120, "forecast_duration_days":18, "benefit_score":7, "risk_exposure":2},
    ])
    assert result["scenarios"][0]["scenario_id"] == "A"
    assert result["decision_status"].startswith("Advisory")


def test_intervention_submission_envelope_requires_owner_and_valid_due_date():
    packet = build_intervention_submission("EX-1", {"title":"Recover milestone", "owner":"PM", "due_date":"2026-12-15"}, "actor-1")
    assert packet["workflow_action"] == "submit_for_approval"
    assert packet["status"] == "Draft"
    with pytest.raises(ValueError): build_intervention_submission("EX-1", {"title":"x"}, "actor-1")
    with pytest.raises(ValueError): build_intervention_submission("EX-1", {"title":"x", "owner":"PM", "due_date":"15/12/2026"}, "actor-1")


def test_v215_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI(); install_routes(app, None, lambda request, operation: operation())
    paths = {r.path for r in app.routes}
    assert "/api/projectone/programmes/calendar-schedule" in paths
    assert "/api/projectone/programmes/risk-simulation" in paths
    assert "/api/projectone/programmes/cost-resource-position" in paths
    assert "/api/projectone/portfolio/scenario-comparison" in paths
    assert "/api/projectone/management/interventions/{exception_id}/submit" in paths


def test_cost_resource_position_rejects_conflicting_capacity_snapshots():
    with pytest.raises(ValueError, match="Conflicting capacity"):
        programme_cost_resource_position([
            {"project_id":"P1", "currency":"NGN", "resources":[{"resource_id":"R", "demand_hours":2, "capacity_hours":8}]},
            {"project_id":"P2", "currency":"NGN", "resources":[{"resource_id":"R", "demand_hours":3, "capacity_hours":6}]},
        ])
