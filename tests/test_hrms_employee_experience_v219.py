"""Regression tests for employee leave self-service, payslip privacy and asset custody."""
import importlib, json, sys
from pathlib import Path
import pytest


def _registry():
    root = Path(__file__).resolve().parents[1]
    app = str(root / "apps" / "velora_erp")
    if app not in sys.path: sys.path.insert(0, app)
    from velora.meta.registry import Registry
    registry = Registry(); registry.load(["velora_erp"])
    return registry


def test_employee_asset_assignment_metadata_and_validation():
    registry = _registry()
    assert "Employee Asset Assignment" in registry._doctypes
    meta = registry._doctypes["Employee Asset Assignment"]
    assert meta.get_field("employee").options == "Employee"
    module = importlib.import_module(meta.controller_module)
    from velora.exceptions import ValidationError
    doc = object.__new__(module.EmployeeAssetAssignment)
    doc.asset_reference="LAP-001"; doc.asset_description="Laptop"; doc.assigned_on="2026-05-01"
    doc.expected_return_date="2026-04-30"; doc.assignment_status="Draft"; doc.issued_by="HR"
    doc.employee_acknowledged=0; doc.returned_on=None; doc.condition_on_return=None; doc.received_by=None
    doc.return_notes=""
    with pytest.raises(ValidationError, match="Expected Return Date"):
        doc.validate()
    doc.expected_return_date="2026-06-01"; doc.assignment_status="Issued"
    with pytest.raises(ValidationError, match="acknowledgement"):
        doc.validate()
    doc.employee_acknowledged=1; doc.validate()
    doc.assignment_status="Returned"; doc.returned_on="2026-05-20"
    with pytest.raises(ValidationError, match="Condition on Return"):
        doc.validate()


def test_hr_employee_experience_routes_registered():
    from fastapi import FastAPI
    from velora.api.hr import install_hr_routes
    app=FastAPI(); install_hr_routes(app, lambda request, fn: fn())
    routes={(r.path, tuple(sorted(r.methods or []))) for r in app.routes}
    assert ("/api/hr/me/leave-applications", ("POST",)) in routes
    assert ("/api/hr/me/payslips", ("GET",)) in routes
    assert ("/api/hr/workforce/dashboard", ("GET",)) in routes


def test_employee_leave_submission_uses_authenticated_employee_and_approved_allocation(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import velora
    from velora.permissions import Session
    from velora.api.hr import install_hr_routes
    calls=[]
    monkeypatch.setattr("velora.api.hr.get_session", lambda: Session(user="staff@example.com", roles=["Employee"]))
    def fake_list(doctype, filters=None, fields=None, **kwargs):
        calls.append((doctype,filters))
        if doctype=="Employee": return [{"name":"EMP-1","employee_name":"Staff","user_account":"staff@example.com"}]
        if doctype=="Leave Allocation": return [{"name":"ALLOC-1","period_start":"2026-01-01","period_end":"2026-12-31"}]
        return []
    class Doc:
        name="LEAVE-1"; workflow_status="Pending Approval"; total_days=2; payroll_treatment="Paid Leave"
        def insert(self, **kwargs): pass
    monkeypatch.setattr(velora,"get_list",fake_list)
    monkeypatch.setattr(velora,"new_doc",lambda doctype,**kwargs: (calls.append((doctype,kwargs)) or Doc()))
    app=FastAPI(); install_hr_routes(app,lambda request,fn:fn())
    response=TestClient(app).post("/api/hr/me/leave-applications",json={"employee":"EMP-OTHER","leave_type":"Annual Leave","from_date":"2026-06-01","to_date":"2026-06-02","reason":"Personal"})
    assert response.status_code==200, response.text
    created=[x for x in calls if x[0]=="Leave Application"][0][1]
    assert created["employee"]=="EMP-1" and created["leave_allocation"]=="ALLOC-1"
    assert created["workflow_status"]=="Pending Approval"


def test_employee_payslip_endpoint_scopes_to_own_posted_slips(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import velora
    from velora.permissions import Session
    from velora.api.hr import install_hr_routes
    monkeypatch.setattr("velora.api.hr.get_session",lambda:Session(user="staff@example.com",roles=["Employee"]))
    calls=[]
    def fake_list(doctype,filters=None,fields=None,**kwargs):
        calls.append((doctype,filters))
        if doctype=="Employee": return [{"name":"EMP-1","employee_name":"Staff","user_account":"staff@example.com"}]
        if doctype=="Salary Slip": return [{"name":"SLIP-1","net_pay":1000,"status":"Posted"}]
        return []
    class Slip:
        lines=[]
    monkeypatch.setattr(velora,"get_list",fake_list)
    monkeypatch.setattr(velora,"get_doc",lambda doctype,name,**kwargs:Slip())
    app=FastAPI();install_hr_routes(app,lambda request,fn:fn())
    response=TestClient(app).get("/api/hr/me/payslips")
    assert response.status_code==200,response.text
    assert response.json()["items"][0]["name"]=="SLIP-1"
    slip_filter=[x[1] for x in calls if x[0]=="Salary Slip"][0]
    assert ["employee","=","EMP-1"] in slip_filter
    assert ["status","in",["Posted","Partially Paid","Paid"]] in slip_filter


def test_hr_workforce_dashboard_requires_hr_role(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from velora.permissions import Session
    from velora.api.hr import install_hr_routes
    monkeypatch.setattr("velora.api.hr.get_session",lambda:Session(user="staff@example.com",roles=["Employee"]))
    app=FastAPI();install_hr_routes(app,lambda request,fn:fn())
    from velora.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        TestClient(app).get("/api/hr/workforce/dashboard")
