"""Metadata and controller tests for Employee Lifecycle / Employee 360 release."""
import importlib, json, sys
from pathlib import Path
import pytest


def _registry():
    project=Path(__file__).resolve().parents[1]
    app_path=str(project/"apps"/"velora_erp")
    if app_path not in sys.path: sys.path.insert(0,app_path)
    from velora.meta.registry import Registry
    registry=Registry(); registry.load(["velora_erp"])
    return registry


def test_employee_lifecycle_doctypes_are_registered_and_linked():
    r=_registry()
    expected={"Employment Contract","Employee Document","Employee Qualification","Employee Status History","Probation Review","Employee Change Request"}
    assert expected.issubset(set(r._doctypes))
    for name in expected:
        dt=r._doctypes[name]
        assert dt.module=="HR"
        assert dt.get_field("employee").options=="Employee"
        assert {p.role for p in dt.permissions if p.read}=={"System Manager","HR Manager","HR Officer"}


def test_contract_rejects_invalid_dates_and_non_hr_approval(monkeypatch):
    r=_registry(); mod=importlib.import_module(r._doctypes["Employment Contract"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    doc=object.__new__(mod.EmploymentContract);doc.employee="EMP-1";doc.start_date="2026-05-01";doc.end_date="2026-04-30";doc.probation_end_date=None;doc.contract_status="Draft"
    with pytest.raises(ValidationError,match="earlier"): doc.validate()
    doc.end_date=None;doc.contract_status="Approved"


def test_document_and_qualification_date_controls(monkeypatch):
    r=_registry(); from velora.exceptions import ValidationError
    d=importlib.import_module(r._doctypes["Employee Document"].controller_module)
    doc=object.__new__(d.EmployeeDocument);doc.issue_date="2026-08-01";doc.expiry_date="2026-07-01";doc.verification_status="Pending"
    with pytest.raises(ValidationError,match="Expiry Date"):doc.validate()
    q=importlib.import_module(r._doctypes["Employee Qualification"].controller_module)
    qual=object.__new__(q.EmployeeQualification);qual.date_awarded="2026-08-01";qual.expiry_date="2026-07-01";qual.verification_status="Pending"
    with pytest.raises(ValidationError,match="Expiry Date"):qual.validate()


def test_probation_requires_extension_date_and_hr_approval(monkeypatch):
    r=_registry();mod=importlib.import_module(r._doctypes["Probation Review"].controller_module)
    from velora.exceptions import ValidationError
    from velora.permissions import Session
    doc=object.__new__(mod.ProbationReview);doc.due_date="2026-05-01";doc.review_date="2026-05-05";doc.extension_end_date=None;doc.recommendation="Extend Probation";doc.approval_status="Draft"
    with pytest.raises(ValidationError,match="Extended Probation End Date"):doc.validate()
    doc.recommendation="Confirm";doc.approval_status="Approved"


def test_hr_metadata_field_types_are_supported():
    project=Path(__file__).resolve().parents[1]
    root=project/"apps"/"velora_erp"/"velora_erp"/"hr"/"doctype"
    allowed={"Data","Text","Int","Float","Currency","Check","Date","Datetime","Select","Link","JSON","Section Break","Column Break","Tab Break","Table"}
    for path in root.glob("*/*.json"):
        data=json.loads(path.read_text())
        assert data["module"]=="HR"
        assert all(f["fieldtype"] in allowed for f in data["fields"])
