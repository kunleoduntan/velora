import pytest
from velora_projectone.projectone.services.enterprise_controls import (
    forecast_portfolio_delivery, analyse_programme_critical_path, build_intervention_centre,
)


def test_delivery_forecast_uses_cpi_spi_and_separates_currency():
    result = forecast_portfolio_delivery([
        {"project_id": "P1", "currency": "NGN", "approved_budget": 1000,
         "actual_cost": 500, "earned_value": 400, "planned_value": 500,
         "planned_duration_days": 100, "elapsed_duration_days": 40},
        {"project_id": "P2", "currency": "USD", "approved_budget": 200,
         "actual_cost": 100, "earned_value": 100, "planned_value": 100},
    ])
    p1 = result["projects"][0]
    assert p1["eac"] == pytest.approx(1250)
    assert p1["spi"] == pytest.approx(.8)
    assert p1["forecast_duration_days"] == pytest.approx(115)
    assert set(result["currency_totals"]) == {"NGN", "USD"}
    assert result["projects"][1]["delivery_health_band"] == "On Track"


def test_delivery_forecast_does_not_invent_eac_when_cpi_unavailable():
    row = forecast_portfolio_delivery([{"project_id": "P", "currency": "NGN",
        "approved_budget": 100, "actual_cost": 0, "earned_value": 0, "planned_value": 0}])["projects"][0]
    assert row["eac"] is None and row["delivery_health_index"] is None
    assert row["delivery_health_band"] == "Not Rated"


def test_delivery_forecast_rejects_duplicate_project_and_bad_financial_input():
    with pytest.raises(ValueError): forecast_portfolio_delivery([
        {"project_id": "P", "currency": "NGN"}, {"project_id": "P", "currency": "NGN"}])
    with pytest.raises(ValueError): forecast_portfolio_delivery([{"project_id": "P", "currency": "NGN", "approved_budget": -1}])


def test_programme_cpm_finds_critical_path_and_float():
    result = analyse_programme_critical_path(
        [{"milestone_id": "A", "project_id": "P1", "duration_days": 5},
         {"milestone_id": "B", "project_id": "P2", "duration_days": 8},
         {"milestone_id": "C", "project_id": "P3", "duration_days": 2}],
        [{"predecessor_id": "A", "successor_id": "C"},
         {"predecessor_id": "B", "successor_id": "C"}],
    )
    assert result["programme_duration_days"] == 10
    assert result["critical_path"] == ["B", "C"]
    by_id = {m["milestone_id"]: m for m in result["milestones"]}
    assert by_id["A"]["total_float_days"] == 3
    assert by_id["B"]["critical"] is True


def test_programme_cpm_rejects_cycle_and_unknown_milestone():
    with pytest.raises(ValueError, match="cycle"):
        analyse_programme_critical_path([{"milestone_id": "A"}, {"milestone_id": "B"}],
            [{"predecessor_id": "A", "successor_id": "B"}, {"predecessor_id": "B", "successor_id": "A"}])
    with pytest.raises(ValueError):
        analyse_programme_critical_path([{"milestone_id": "A"}], [{"predecessor_id": "A", "successor_id": "X"}])


def test_intervention_centre_prioritises_overdue_and_reports_missing_actions():
    result = build_intervention_centre(
        [{"exception_id": "E1", "project_id": "P1", "severity": "Critical", "due_period": "2026-10"},
         {"exception_id": "E2", "project_id": "P2", "severity": "High", "due_period": "2026-12"}],
        [{"exception_id": "E1", "owner": "Manager", "action": "Recover schedule", "status": "In Progress", "due_period": "2026-10"}],
        as_of_period="2026-11")
    assert result["interventions"][0]["exception_id"] == "E1"
    assert result["overdue_count"] == 1
    assert result["without_action_count"] == 1


def test_intervention_centre_rejects_duplicate_or_invalid_action_status():
    with pytest.raises(ValueError):
        build_intervention_centre([], [{"exception_id": "E", "status": "Unknown"}])
    with pytest.raises(ValueError):
        build_intervention_centre([], [{"exception_id": "E"}, {"exception_id": "E"}])


def test_enterprise_control_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    paths = {route.path for route in app.routes}
    assert "/api/projectone/portfolio/delivery-forecast" in paths
    assert "/api/projectone/programmes/critical-path" in paths
    assert "/api/projectone/management/intervention-centre" in paths
