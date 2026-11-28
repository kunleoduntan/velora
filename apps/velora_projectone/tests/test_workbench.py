from velora_projectone.projectone.services.workbench import build_task_board, resource_capacity_warnings


def test_task_board_lanes_and_action_centre_are_deterministic():
    tasks = [
        {"name":"T-1", "title":"Late", "status":"In Progress", "planned_finish":"2026-11-18", "assignee":"u1", "priority":"Critical"},
        {"name":"T-2", "title":"Due soon", "status":"Open", "planned_finish":"2026-11-25", "assignee":None, "priority":"Normal"},
        {"name":"T-3", "title":"Done", "status":"Completed", "planned_finish":"2026-11-01"},
        {"name":"T-4", "title":"Paused", "status":"On Hold", "planned_finish":"2026-12-01", "assignee":"u2"},
    ]
    result = build_task_board(tasks, as_of="2026-11-21")
    assert result["total"] == 4
    assert result["counts"] == {"overdue": 1, "due_within_7_days": 1, "blocked": 1, "unassigned": 1}
    assert result["action_centre"]["overdue"][0]["days_overdue"] == 3
    assert result["lanes"]["Completed"][0]["name"] == "T-3"


def test_task_board_filters_assignee_and_priority():
    rows = [{"name":"1", "title":"A", "status":"Open", "assignee":"u1", "priority":"High"},
            {"name":"2", "title":"B", "status":"Open", "assignee":"u2", "priority":"High"}]
    result = build_task_board(rows, as_of="2026-11-21", assignee="u1", priority="High")
    assert result["total"] == 1


def test_resource_capacity_warning_only_for_approved_allocations():
    tasks = [{"assignee":"u1", "planned_start":"2026-11-16", "planned_finish":"2026-11-20", "estimated_hours":45, "status":"In Progress"}]
    allocations = [
        {"resource":"u1", "start_date":"2026-11-01", "end_date":"2026-11-30", "planned_hours":40, "status":"In Progress", "approved_by":"pm"},
        {"resource":"u1", "start_date":"2026-11-01", "end_date":"2026-11-30", "planned_hours":100, "status":"Draft", "approved_by":"pm"},
    ]
    warnings = resource_capacity_warnings(tasks, allocations)
    assert len(warnings) == 1
    assert warnings[0]["excess_hours"] == 5
    assert warnings[0]["severity"] == "Medium"


def test_workbench_and_task_governance_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    paths = {route.path for route in app.routes}
    assert "/api/projectone/workbench/projects/{project_id}" in paths
    assert "/api/projectone/tasks/{task_id}/workflow/{action}" in paths
    assert "/api/projectone/tasks/{task_id}/reassign" in paths
    assert "/api/projectone/tasks/{task_id}/comments" in paths
    assert "/api/projectone/tasks/{task_id}/activity" in paths
    assert "/api/projectone/workflow/inbox" in paths


def test_enterprise_capacity_and_escalation_routes_are_registered():
    from fastapi import FastAPI
    from velora_projectone.api_routes import install_routes
    app = FastAPI()
    install_routes(app, None, lambda request, operation: operation())
    paths = {route.path for route in app.routes}
    assert "/api/projectone/capacity/enterprise" in paths
    assert "/api/projectone/workbench/projects/{project_id}/escalations" in paths
