"""Recruitment and onboarding metadata and business-rule tests."""
import json, sys
from pathlib import Path

def _registry():
    project=Path(__file__).resolve().parents[1]
    app=str(project/"apps"/"velora_erp")
    if app not in sys.path: sys.path.insert(0,app)
    from velora.meta.registry import Registry
    r=Registry(); r.load(["velora_erp"]); return r

def test_recruitment_and_onboarding_doctypes_register():
    r=_registry()
    expected={"Job Requisition","Candidate","Job Posting","Job Application","Interview","Job Offer","Onboarding Plan","Onboarding Task"}
    assert expected.issubset(set(r._doctypes))

def test_candidate_is_not_employee_and_conversion_is_explicit():
    r=_registry(); c=r._doctypes["Candidate"]
    assert c.get_field("converted_employee").options == "Employee"
    assert c.get_field("candidate_status").choices[-1] == "Talent Pool"

def test_offer_acceptance_and_conversion_are_separate_fields():
    r=_registry(); o=r._doctypes["Job Offer"]
    assert o.get_field("decision").choices == ["Pending","Accepted","Declined","Expired"]
    assert o.get_field("converted_employee").options == "Employee"

def test_onboarding_tasks_have_ownership_due_date_and_evidence():
    r=_registry(); t=r._doctypes["Onboarding Task"]
    assert t.get_field("assigned_to") and t.get_field("due_date") and t.get_field("evidence_reference")

def test_hr_recruitment_metadata_uses_supported_field_types():
    root=Path(__file__).resolve().parents[1]/"apps"/"velora_erp"/"velora_erp"/"hr"/"doctype"
    supported={"Data","Text","Int","Float","Currency","Check","Date","Datetime","Select","Link","JSON","Section Break","Column Break","Tab Break","Table"}
    for p in root.glob("*/*.json"):
        d=json.loads(p.read_text())
        assert d["module"] == "HR"
        assert all(x["fieldtype"] in supported for x in d["fields"])
