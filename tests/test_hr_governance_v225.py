from datetime import date, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _app():
    from velora.api.hr_governance import install_hr_governance_routes
    app=FastAPI(); install_hr_governance_routes(app,lambda request,fn:fn()); return app


def test_hr_governance_routes_registered():
    routes={(r.path,tuple(sorted(r.methods or []))) for r in _app().routes}
    expected={("/api/hr/handovers",("GET",)),("/api/hr/handovers",("POST",)),
      ("/api/hr/handovers/{handover_name}/transition",("POST",)),
      ("/api/hr/handovers/{handover_name}/items/{item_index}",("POST",)),
      ("/api/hr/policies",("GET",)),("/api/hr/policies",("POST",)),
      ("/api/hr/policies/{policy_name}/versions",("POST",)),
      ("/api/hr/policies/{policy_name}/versions/{version_number}/transition",("POST",)),
      ("/api/hr/policies/{policy_name}/acknowledgements",("POST",)),
      ("/api/hr/policy-acknowledgements/{ack_name}/acknowledge",("POST",)),
      ("/api/hr/policy-acknowledgements",("GET",))}
    assert expected.issubset(routes)


def test_handover_create_requires_matching_employee_source(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="hr",roles=["HR Manager"]))
    import velora
    class Source: employee="EMP-2"; workflow_status="Approved"; from_date="2026-12-01"; to_date="2026-12-05"
    monkeypatch.setattr(velora,"get_doc",lambda *a,**k:Source())
    with pytest.raises(Exception,match="does not belong"):
        TestClient(_app()).post("/api/hr/handovers",json={"employee":"EMP-1","handover_type":"Leave","source_reference":"LEAVE-1","handover_items":[{"task":"Transfer open work"}]})


def test_handover_requires_all_tasks_accepted_before_acceptance(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="hr",roles=["HR Manager"]))
    import velora
    class Doc:
        name="HO-1"; handover_status="Submitted"; handover_items=[{"task":"Transfer work","handover_status":"Submitted"}]; outstanding_count=1
        def save(self,**kwargs): pass
    monkeypatch.setattr(velora,"get_doc",lambda *a,**k:Doc())
    with pytest.raises(Exception,match="Every handover task"):
        TestClient(_app()).post("/api/hr/handovers/HO-1/transition",json={"action":"Accept"})


def test_handover_item_recipient_acceptance_updates_outstanding_count(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="hr",roles=["HR Officer"]))
    import velora
    class Doc:
        name="HO-2"; handover_status="Submitted"; handover_items=[{"task":"Transfer work","handover_status":"Submitted"}]; outstanding_count=1
        def save(self,**kwargs): pass
    doc=Doc(); monkeypatch.setattr(velora,"get_doc",lambda *a,**k:doc)
    response=TestClient(_app()).post("/api/hr/handovers/HO-2/items/0",json={"handover_status":"Accepted","evidence_reference":"DOC-1"})
    assert response.status_code==200
    assert response.json()["outstanding_count"]==0
    assert doc.handover_items[0]["handover_status"]=="Accepted"


def test_policy_version_publish_requires_approval_and_future_effective_date(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="hr",roles=["HR Manager"]))
    import velora
    class Row(dict): __getattr__=dict.get; __setattr__=dict.__setitem__
    row=Row(version_number="2.0",version_status="Approved",effective_from=(date.today()-timedelta(days=1)).isoformat(),approved_by="hr")
    class Doc:
        name="POL-1"; policy_status="In Review"; current_version="1.0"; review_cycle_months=12; versions=[row]
        def save(self,**kwargs): pass
    doc=Doc(); monkeypatch.setattr(velora,"get_doc",lambda *a,**k:doc)
    with pytest.raises(Exception,match="effective date today or in the future"):
        TestClient(_app()).post("/api/hr/policies/POL-1/versions/2.0/transition",json={"action":"Publish"})


def test_policy_acknowledgement_is_bound_to_published_version(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="hr",roles=["HR Officer"]))
    import velora
    class V: version_number="1.0"; version_status="Approved"
    class Policy: name="POL-1"; current_version="1.0"; versions=[V()]
    monkeypatch.setattr(velora,"get_doc",lambda *a,**k:Policy())
    with pytest.raises(Exception,match="exact Published policy version"):
        TestClient(_app()).post("/api/hr/policies/POL-1/acknowledgements",json={"employees":["EMP-1"]})


def test_non_hr_cannot_administer_handovers(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="staff",roles=["Employee"]))
    with pytest.raises(Exception,match="not permitted"):
        TestClient(_app()).get("/api/hr/handovers")


def test_employee_policy_library_exposes_only_general_published_policies(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="staff@example.com",roles=["Employee"]))
    import velora
    monkeypatch.setattr(velora,"get_list",lambda doctype,filters=None,fields=None,**kw: (
        [{"name":"EMP-1"}] if doctype=="Employee" else
        [{"name":"POL-1","policy_code":"GEN-01","policy_title":"General Conduct","current_version":"1.0","confidentiality":"All Employees","acknowledgement_required":1}] if doctype=="HR Policy Document" else
        [{"name":"ACK-1","acknowledgement_status":"Pending"}] if doctype=="HR Policy Acknowledgement" else []))
    class V: version_number="1.0"; version_status="Published"; version_content="Policy body"; effective_from="2026-01-01"; change_summary="Initial"; attachment=None
    class Policy: versions=[V()]
    monkeypatch.setattr(velora,"get_doc",lambda *a,**k:Policy())
    response=TestClient(_app()).get("/api/hr/policies/available")
    assert response.status_code==200
    assert response.json()["items"][0]["version_content"]=="Policy body"
    assert response.json()["items"][0]["acknowledgement"]["name"]=="ACK-1"


def test_employee_cannot_accept_another_employees_handover(monkeypatch):
    from velora.permissions import Session
    monkeypatch.setattr("velora.api.hr_governance.get_session",lambda:Session(user="staff@example.com",roles=["Employee"]))
    import velora
    class Doc:
        name="HO-3"; handover_status="Submitted"; receiving_employee="EMP-2"; handover_items=[{"task":"Transfer work","handover_status":"Submitted"}]; outstanding_count=1
    monkeypatch.setattr(velora,"get_doc",lambda *a,**k:Doc())
    monkeypatch.setattr(velora,"get_list",lambda *a,**k:[{"name":"EMP-1"}])
    with pytest.raises(Exception,match="designated receiving employee"):
        TestClient(_app()).post("/api/hr/handovers/HO-3/transition",json={"action":"Accept"})
