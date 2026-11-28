from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _app():
    from velora.api.hr_operations import install_hr_operations_routes
    app = FastAPI()
    install_hr_operations_routes(app, lambda request, fn: fn())
    return app


def test_hr_operations_routes_registered():
    app = _app()
    routes = {(r.path, tuple(sorted(r.methods or []))) for r in app.routes}
    assert ("/api/hr/recruitment/pipeline", ("GET",)) in routes
    assert ("/api/hr/recruitment/offers/{offer_name}/decision", ("POST",)) in routes
    assert ("/api/hr/leave/administration", ("GET",)) in routes
    assert ("/api/hr/leave/payroll-handoff-preview", ("GET",)) in routes
    assert ("/api/hr/reports/workforce", ("GET",)) in routes


def test_recruitment_pipeline_builds_stage_and_offer_metrics(monkeypatch):
    import velora
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="hr@example.com", roles=["HR Manager"]))
    def fake_list(doctype, filters=None, fields=None, **kwargs):
        if doctype == "Job Requisition":
            return [{"name":"REQ-1","requisition_title":"Analyst","department":"Finance","vacancy_count":2,"requisition_status":"Approved"}]
        if doctype == "Job Application":
            return [{"name":"APP-1","application_stage":"Interview"},{"name":"APP-2","application_stage":"Offer"}]
        if doctype == "Job Offer":
            return [{"name":"OFF-1","requisition":"REQ-1","decision":"Accepted","converted_employee":None}]
        return []
    monkeypatch.setattr(velora, "get_list", fake_list)
    result = TestClient(_app()).get("/api/hr/recruitment/pipeline")
    assert result.status_code == 200
    summary = result.json()["summary"]
    assert summary["approved_vacancies"] == 2
    assert summary["applications_by_stage"] == {"Interview": 1, "Offer": 1}
    assert summary["accepted_offers_pending_employee_conversion"] == 1


def test_offer_decision_requires_approved_pending_and_does_not_create_employee(monkeypatch):
    from velora.permissions import Session
    from fastapi.testclient import TestClient
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="hr@example.com", roles=["HR Officer"]))
    class Offer:
        name = "OFF-1"
        approval_status = "Approved"
        decision = "Pending"
        offer_expiry_date = (date.today() + timedelta(days=2)).isoformat()
        converted_employee = None
        saved = False
        def save(self, **kwargs): self.saved = True
    offer = Offer()
    import velora
    monkeypatch.setattr(velora, "get_doc", lambda *a, **k: offer)
    result = TestClient(_app()).post("/api/hr/recruitment/offers/OFF-1/decision", json={"decision":"Accepted"})
    assert result.status_code == 200
    assert offer.decision == "Accepted" and offer.saved
    assert result.json()["employee_created"] is False


def test_offer_decision_rejects_unapproved_offer(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="hr@example.com", roles=["HR Manager"]))
    class Offer:
        name="OFF-2"; approval_status="Pending Approval"; decision="Pending"; offer_expiry_date=None
    import velora
    monkeypatch.setattr(velora, "get_doc", lambda *a, **k: Offer())
    from velora.exceptions import ValidationError
    with pytest.raises(ValidationError, match="approved Job Offer"):
        TestClient(_app()).post("/api/hr/recruitment/offers/OFF-2/decision", json={"decision":"Accepted"})


def test_leave_payroll_handoff_is_preview_only_and_filters_company(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="hr@example.com", roles=["HR Manager"]))
    calls=[]
    import velora
    def fake_list(doctype, filters=None, fields=None, **kwargs):
        calls.append((doctype, filters))
        if doctype == "Employee":
            return [{"name":"EMP-1","employee_name":"A Staff","department":"Finance","company":"ACME"}]
        if doctype == "Leave Application":
            return [{"name":"LEAVE-1","employee":"EMP-1","total_days":3,"payroll_treatment":"Paid Leave","workflow_status":"Approved"}]
        return []
    monkeypatch.setattr(velora, "get_list", fake_list)
    result=TestClient(_app()).get("/api/hr/leave/payroll-handoff-preview?start_date=2026-01-01&end_date=2026-01-31&company=ACME")
    assert result.status_code==200
    assert result.json()["summary"]["days_by_payroll_treatment"] == {"Paid Leave":3.0}
    assert "Preview only" in result.json()["posting_status"]
    assert ("Salary Slip", None) not in calls


def test_workforce_report_validates_period_and_returns_movement(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="hr@example.com", roles=["HR Manager"]))
    import velora
    def fake_list(doctype, filters=None, fields=None, **kwargs):
        if doctype == "Employee":
            return [{"name":"EMP-1","employee_name":"New Hire","department":"Finance","employee_type":"Permanent","date_of_joining":"2026-02-01","disabled":False}]
        if doctype == "Attendance": return [{"name":"ATT-1","employee":"EMP-1","status":"Present"}]
        if doctype == "Leave Application": return [{"name":"LV-1","employee":"EMP-1","total_days":2,"workflow_status":"Approved"}]
        if doctype == "Employee Separation": return []
        return []
    monkeypatch.setattr(velora, "get_list", fake_list)
    client=TestClient(_app())
    from velora.exceptions import ValidationError
    with pytest.raises(ValidationError, match="valid reporting date range"):
        client.get("/api/hr/reports/workforce?start_date=2026-03-01&end_date=2026-02-01")
    good=client.get("/api/hr/reports/workforce?start_date=2026-01-01&end_date=2026-03-01")
    assert good.status_code==200
    summary=good.json()["summary"]
    assert summary["joiners"]==1 and summary["net_headcount_movement"]==1
    assert summary["approved_leave_days"]==2


def test_hr_operations_routes_reject_non_hr_user(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_operations.get_session", lambda: Session(user="staff@example.com", roles=["Employee"]))
    from velora.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied):
        TestClient(_app()).get("/api/hr/recruitment/pipeline")
