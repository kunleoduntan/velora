from pathlib import Path
import json

PROJECT=Path(__file__).resolve().parents[1]


def test_employee_has_unique_login_mapping_for_self_service():
    employee=json.loads((PROJECT/"apps/velora_erp/velora_erp/hr/doctype/employee/employee.json").read_text())
    field=next(x for x in employee["fields"] if x["fieldname"]=="user_account")
    assert field["fieldtype"]=="Data" and field["unique"] is True


def test_employee_and_manager_performance_portal_routes_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app,lambda request,fn: fn())
    paths={r.path for r in app.routes}
    expected={
      "/api/hr/performance/me",
      "/api/hr/performance/me/goals/{goal_name}/progress",
      "/api/hr/performance/me/check-ins",
      "/api/hr/performance/me/reviews/{review_name}/acknowledge",
      "/api/hr/performance/manager/team",
      "/api/hr/performance/manager/team/{employee_name}/check-ins",
    }
    assert expected <= paths


def test_employee_and_manager_workspaces_are_published():
    setup=(PROJECT/"apps/velora_erp/velora_erp/setup.py").read_text()
    assert "def ensure_employee_performance_workspaces()" in setup
    assert '"My Performance"' in setup and '"Team Performance"' in setup
    assert "ensure_employee_performance_workspaces()" in setup


def test_portal_uses_reporting_assignment_for_direct_reports():
    source=(PROJECT/"velora/api/hr.py").read_text()
    assert 'get_list("Reporting Assignment"' in source
    assert '["assignment_status","=","Approved"]' in source
    assert '["reports_to","=",manager_name]' in source


def test_employee_portal_does_not_accept_client_supplied_employee_identity():
    source=(PROJECT/"velora/api/hr.py").read_text()
    assert 'filters=[["user_account","=",session.user]]' in source
    assert 'Employees may update only their own assigned goals.' in source
    assert 'Managers may create check-ins only for current direct reports.' in source
