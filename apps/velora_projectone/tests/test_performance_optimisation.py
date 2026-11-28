import pytest
from velora_projectone.projectone.services.performance_optimisation import (
    forecast_earned_value, analyse_schedule_trend, optimise_resource_conflicts,
    portfolio_profitability_trend, schedule_benefit_reviews, build_management_alerts,
)


def test_evm_cpi_forecast_and_tcpi():
    r=forecast_earned_value(pv=80,ev=70,ac=75,bac=120,method="cpi")
    assert r["cpi"] == pytest.approx(70/75)
    assert r["eac"] == pytest.approx(120/(70/75))
    assert r["tcpi"] == pytest.approx(50/45)
    assert r["vac"] < 0


def test_evm_bottom_up_requires_remaining_work_and_rejects_negative():
    with pytest.raises(ValueError): forecast_earned_value(pv=1,ev=1,ac=1,bac=2,method="bottom_up")
    with pytest.raises(ValueError): forecast_earned_value(pv=-1,ev=1,ac=1,bac=2)
    assert forecast_earned_value(pv=1,ev=1,ac=1,bac=2,method="bottom_up",remaining_work=3)["eac"] == 4


def test_schedule_trend_sorts_periods_and_forecasts_direction():
    r=analyse_schedule_trend([{"period":"2026-03","variance_days":10},{"period":"2026-01","variance_days":20},{"period":"2026-02","variance_days":15}])
    assert r["trend"] == "Improving"
    assert r["next_period_forecast_variance_days"] == pytest.approx(5)


def test_schedule_trend_rejects_duplicate_periods():
    with pytest.raises(ValueError): analyse_schedule_trend([{"period":"x","variance_days":1},{"period":"x","variance_days":2}])


def test_resource_optimisation_allocates_by_priority_and_exposes_unassigned():
    r=optimise_resource_conflicts([
        {"activity_id":"B","resource_id":"R","period":"P","hours":8,"priority":2},
        {"activity_id":"A","resource_id":"R","period":"P","hours":8,"priority":1}],
        [{"resource_id":"R","period":"P","available_hours":10}])
    assert r["allocations"][0]["activity_id"] == "A"
    assert r["allocations"][1]["unassigned_hours"] == 6


def test_profitability_never_mixes_currency():
    r=portfolio_profitability_trend([
        {"period":"2026-Q1","currency":"NGN","revenue":100,"cost":70},
        {"period":"2026-Q1","currency":"USD","revenue":50,"cost":20}])
    assert len(r["periods"]) == 2
    assert r["periods"][0]["contribution_margin"] == 30


def test_benefit_reviews_identify_overdue_and_missing_measurement():
    r=schedule_benefit_reviews([{"benefit_id":"B1","next_review_period":"2026-Q1","target_value":100,"actual_value":90}],"2026-Q2")
    assert r["overdue_count"] == 1 and r["missing_measurement_count"] == 0


def test_management_alerts_sort_and_assign_owner():
    r=build_management_alerts([
        {"exception_id":"E1","severity":"Low"},
        {"exception_id":"E2","severity":"Critical"}],owners={"E2":"PMO"})
    assert r["alerts"][0]["exception_id"] == "E2"
    assert r["unassigned_count"] == 1


def test_evm_duration_forecast_uses_elapsed_plus_remaining_adjusted_by_spi():
    r=forecast_earned_value(pv=80,ev=70,ac=75,bac=120,method="cpi",
                            planned_duration_days=100,elapsed_duration_days=40)
    assert r["duration_forecast_days"] == pytest.approx(40 + 60/(70/80))
