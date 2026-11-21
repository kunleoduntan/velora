"""Regression tests for HR core, employee self-service and exit/relations controls."""
import importlib, json, sys
from pathlib import Path
import pytest


def _registry():
    project = Path(__file__).resolve().parents[1]
    app = str(project / "apps" / "velora_erp")
    if app not in sys.path:
        sys.path.insert(0, app)
    from velora.meta.registry import Registry
    registry = Registry()
    registry.load(["velora_erp"])
    return registry


def test_separation_and_relations_doctypes_register_with_child_tables():
    registry = _registry()
    expected = {"Employee Separation", "Exit Clearance Item", "Employee Relations Case", "Employee Relations Action"}
    assert expected.issubset(set(registry._doctypes))
    separation = registry._doctypes["Employee Separation"]
    assert separation.get_field("employee").options == "Employee"
    assert separation.get_field("clearance_items").options == "Exit Clearance Item"
    assert registry._doctypes["Exit Clearance Item"].istable
    case = registry._doctypes["Employee Relations Case"]
    assert case.get_field("actions").options == "Employee Relations Action"
    assert registry._doctypes["Employee Relations Action"].istable


def test_separation_rejects_invalid_dates_and_unapproved_closure(monkeypatch):
    module = importlib.import_module(_registry()._doctypes["Employee Separation"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    doc = object.__new__(module.EmployeeSeparation)
    doc.notice_date = "2026-05-10"; doc.last_working_date = "2026-05-09"; doc.reason = "Resignation"
    doc.approval_status = "Not Submitted"; doc.workflow_status = "Draft"; doc.clearance_items = []
    with pytest.raises(ValidationError, match="earlier than Notice Date"):
        doc.validate()
    doc.last_working_date = "2026-06-01"; doc.workflow_status = "Closed"; doc.approval_status = "Approved"
    monkeypatch.setattr(module, "get_session", lambda: Session(user="hr-manager", roles=["HR Manager"]))
    with pytest.raises(ValidationError, match="All exit clearance items"):
        doc.validate()


def test_separation_cannot_close_until_clearance_and_finance_handoff_complete(monkeypatch):
    module = importlib.import_module(_registry()._doctypes["Employee Separation"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    class Item:
        clearance_area = "IT"
        clearance_status = "Cleared"
        completed_on = "2026-06-01"
    doc = object.__new__(module.EmployeeSeparation)
    doc.notice_date="2026-05-01"; doc.last_working_date="2026-06-01"; doc.reason="Retirement"
    doc.approval_status="Approved"; doc.workflow_status="Closed"; doc.clearance_items=[Item()]
    doc.final_settlement_status="Pending Finance"; doc.finance_reference=None
    monkeypatch.setattr(module, "get_session", lambda: Session(user="hr-manager", roles=["HR Manager"]))
    with pytest.raises(ValidationError, match="Finance final settlement"):
        doc.validate()
    doc.final_settlement_status="Completed"
    with pytest.raises(ValidationError, match="Finance settlement reference"):
        doc.validate()


def test_relations_case_requires_investigator_and_resolution_evidence(monkeypatch):
    module = importlib.import_module(_registry()._doctypes["Employee Relations Case"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    monkeypatch.setattr(module, "get_session", lambda: Session(user="hr-manager", roles=["HR Manager"]))
    doc = object.__new__(module.EmployeeRelationsCase)
    doc.reported_date="2026-05-10"; doc.incident_date="2026-05-11"; doc.target_resolution_date=None
    doc.case_status="Open"; doc.assigned_investigator=None; doc.actions=[]
    with pytest.raises(ValidationError, match="later than Reported Date"):
        doc.validate()
    doc.incident_date=None; doc.case_status="Under Investigation"
    with pytest.raises(ValidationError, match="Assign an investigator"):
        doc.validate()
    doc.assigned_investigator="Investigator A"; doc.case_status="Closed"; doc.resolution_summary=""; doc.outcome=None
    with pytest.raises(ValidationError, match="resolution summary"):
        doc.validate()


def test_employee_service_request_is_bound_to_authenticated_employee(monkeypatch):
    module = importlib.import_module(_registry()._doctypes["HR Service Request"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    class Employee:
        disabled = False
        user_account = "employee@example.com"
    monkeypatch.setattr(module, "get_session", lambda: Session(user="employee@example.com", roles=["Employee"]))
    monkeypatch.setattr(module, "get_doc", lambda doctype, name, **k: Employee() if name == "EMP-001" else type("OtherEmployee", (), {"disabled": False, "user_account": "someone-else@example.com"})())
    doc = object.__new__(module.HRServiceRequest)
    doc.employee="EMP-001"; doc.subject="Letter"; doc.details="Need employment letter"
    doc.request_status="Open"; doc.assigned_to=None; doc.resolution=None; doc.resolved_on=None
    doc.validate()
    doc.employee="EMP-002"
    with pytest.raises(ValidationError, match="own active Employee account"):
        doc.validate()


def test_hr_metadata_has_supported_field_types_and_valid_module_ownership():
    root = Path(__file__).resolve().parents[1] / "apps" / "velora_erp" / "velora_erp" / "hr" / "doctype"
    supported = {"Data", "Text", "Int", "Float", "Currency", "Check", "Date", "Datetime", "Select", "Link", "JSON", "Section Break", "Column Break", "Tab Break", "Table"}
    for path in root.glob("*/*.json"):
        data = json.loads(path.read_text())
        assert data["module"] == "HR", path
        assert all(field["fieldtype"] in supported for field in data["fields"]), path


def test_employee_self_service_routes_and_frontend_are_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app = FastAPI()
    install_hr_routes(app, lambda request, fn: fn())
    routes = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}
    assert ("/api/hr/me/overview", ("GET",)) in routes
    assert ("/api/hr/me/requests", ("GET",)) in routes
    assert ("/api/hr/me/requests", ("POST",)) in routes
    project = Path(__file__).resolve().parents[1]
    frontend = (project / "frontend/src/components/EmployeeSelfService.tsx").read_text()
    assert "My HR Services" in frontend and "Submit HR Request" in frontend
    assert "hr-self-service" in (project / "frontend/src/router.ts").read_text()


def test_employee_self_service_queries_only_existing_doctype_fields():
    project = Path(__file__).resolve().parents[1]
    root = project / "apps/velora_erp/velora_erp/hr/doctype"
    expected = {
        "attendance": {"attendance_date", "status", "worked_hours", "approval_status"},
        "leave_application": {"leave_type", "from_date", "to_date", "total_days", "workflow_status", "payroll_treatment"},
        "employee_document": {"document_type", "document_title", "issue_date", "expiry_date", "verification_status"},
    }
    for slug, fields in expected.items():
        meta = json.loads((root / slug / f"{slug}.json").read_text())
        actual = {field["fieldname"] for field in meta["fields"]}
        assert fields <= actual, slug
    source = (project / "velora/api/hr.py").read_text()
    assert '"worked_hours"' in source and '"working_hours"' not in source


def test_employee_self_service_overview_uses_session_mapping_and_scoped_lists(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import velora
    from velora.permissions import Session
    from velora.api.hr import install_hr_routes
    calls = []
    def fake_list(doctype, filters=None, fields=None, **kwargs):
        calls.append((doctype, filters, fields))
        if doctype == "Employee":
            return [{"name": "EMP-100", "employee_name": "Test Employee", "department": "Finance", "designation": "Analyst", "user_account": "staff@example.com"}]
        if doctype == "Attendance":
            return [{"name": "ATT-1", "attendance_date": "2026-11-16", "status": "Present", "worked_hours": 8, "approval_status": "Approved"}]
        return []
    monkeypatch.setattr(velora, "get_list", fake_list)
    monkeypatch.setattr("velora.api.hr.get_session", lambda: Session(user="staff@example.com", roles=["Employee"]))
    app = FastAPI(); install_hr_routes(app, lambda request, fn: fn())
    response = TestClient(app).get("/api/hr/me/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["employee"]["name"] == "EMP-100"
    assert payload["attendance"][0]["worked_hours"] == 8
    employee_filter = calls[0][1]
    assert employee_filter == [["user_account", "=", "staff@example.com"]]
    assert all(filters and ["employee", "=", "EMP-100"] in filters for doctype, filters, _ in calls[1:])
