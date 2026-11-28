from decimal import Decimal
import pytest
from velora_projectone.projectone.services.resource_levelling import (
    build_workload_forecast, preview_resource_levelling,
)


def test_weekly_forecast_aggregates_daily_values_and_reports_utilisation():
    rows = [
        {"resource_id":"R1", "date":"2026-11-16", "capacity_hours":8, "demand_hours":6, "overallocated":False},
        {"resource_id":"R1", "date":"2026-11-17", "capacity_hours":8, "demand_hours":10, "overallocated":True},
        {"resource_id":"R2", "date":"2026-11-17", "capacity_hours":8, "demand_hours":4, "overallocated":False},
    ]
    result = build_workload_forecast(rows)
    assert result["periods"][0]["period"] == "2026-W47"
    assert result["periods"][0]["capacity_hours"] == 24
    assert result["periods"][0]["demand_hours"] == 20
    assert result["periods"][0]["utilisation_ratio"] == Decimal(20) / Decimal(24)
    assert result["periods"][0]["resource_count"] == 2


def test_monthly_forecast_and_invalid_bucket():
    result = build_workload_forecast([{"resource_id":"R", "date":"2026-12-01",
        "capacity_hours":8, "demand_hours":9, "overallocated":True}], bucket="month")
    assert result["periods"][0]["period"] == "2026-12"
    assert result["periods"][0]["overallocated_days"] == 1
    with pytest.raises(ValueError, match="bucket"):
        build_workload_forecast([], bucket="quarter")


def test_levelling_prioritises_critical_tasks_and_distributes_across_window():
    profiles = [{"name":"RP1", "resource_id":"R1", "display_name":"Ada"}]
    capacity = [
        {"resource_id":"R1", "date":"2026-11-23", "capacity_hours":4},
        {"resource_id":"R1", "date":"2026-11-24", "capacity_hours":4},
    ]
    tasks = [
        {"name":"LOW", "resource_profile":"RP1", "priority":"Low", "planned_start":"2026-11-23", "planned_finish":"2026-11-24", "estimated_hours":6},
        {"name":"CRIT", "resource_profile":"RP1", "priority":"Critical", "planned_start":"2026-11-23", "planned_finish":"2026-11-24", "estimated_hours":6},
    ]
    result = preview_resource_levelling(tasks, profiles, capacity)
    by_id = {x["task"]: x for x in result["allocations"]}
    assert by_id["CRIT"]["assigned_hours"] == 6
    assert by_id["LOW"]["assigned_hours"] == 2
    assert by_id["LOW"]["unassigned_hours"] == 4
    assert result["unassigned_hours"] == 4
    assert result["schedule_dates_changed"] is False
    assert result["resource_reservations_created"] is False


def test_levelling_does_not_guess_ambiguous_resource_aliases():
    profiles = [{"name":"RP1", "resource_id":"R1", "display_name":"Sam"},
                {"name":"RP2", "resource_id":"R2", "display_name":"Sam"}]
    tasks = [{"name":"T1", "assignee":"Sam", "planned_start":"2026-11-23",
              "planned_finish":"2026-11-23", "estimated_hours":5}]
    result = preview_resource_levelling(tasks, profiles,
        [{"resource_id":"R1", "date":"2026-11-23", "capacity_hours":8},
         {"resource_id":"R2", "date":"2026-11-23", "capacity_hours":8}])
    assert result["allocations"][0]["resource_id"] is None
    assert result["unassigned_hours"] == 5


def test_levelling_rejects_invalid_date_and_negative_hours():
    profile = [{"name":"RP1", "resource_id":"R1"}]
    capacity = [{"resource_id":"R1", "date":"2026-11-23", "capacity_hours":8}]
    with pytest.raises(ValueError, match="planned_start"):
        preview_resource_levelling([{"name":"T", "resource_profile":"RP1", "planned_start":"bad",
            "planned_finish":"2026-11-23", "estimated_hours":2}], profile, capacity)
    with pytest.raises(ValueError, match="non-negative"):
        preview_resource_levelling([{"name":"T", "resource_profile":"RP1", "planned_start":"2026-11-23",
            "planned_finish":"2026-11-23", "estimated_hours":-2}], profile, capacity)


def test_capacity_forecast_and_levelling_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}
    assert ("/api/projectone/capacity/forecast", ("GET",)) in routes
    assert ("/api/projectone/capacity/levelling-preview", ("POST",)) in routes


def test_project_collaboration_feed_route_is_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    assert any(route.path == "/api/projectone/projects/{project_id}/collaboration-feed"
               and "GET" in (route.methods or set()) for route in app.routes)
