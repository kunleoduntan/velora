"""Department staff budgets and the request to employ (v2.83)."""
from datetime import date
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora_erp.setup import after_install


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'sb.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _base():
    d = new_doc("Department", department_code="FIN", department_name="Finance").insert(ignore_permissions=True)
    g = new_doc("Designation", designation_code="ACC", designation_name="Accountant").insert(ignore_permissions=True)
    return d, g


def _budget(d, g, head=3, status="Approved", **kw):
    return new_doc("Department Staff Budget", budget_title="FY26", department=d.name, from_date=date(2026, 1, 1), to_date=date(2026, 12, 31),
                   budget_status=status, lines=[{"designation": g.name, "budgeted_headcount": head, "monthly_cost_per_head": 500000}], **kw).insert(ignore_permissions=True)


def _req(d, g, n=1, status="Pending Approval"):
    return new_doc("Job Requisition", requisition_title="Accountant", department=d.name, designation=g.name, vacancy_count=n,
                   target_start_date=date(2026, 6, 1), requisition_status=status, business_justification="Growth").insert(ignore_permissions=True)


def _emp(code, d, g):
    return new_doc("Employee", employee_code=code, employee_name=code, employee_type="Permanent", date_of_joining=date(2020, 1, 1), department=d.name, designation=g.name).insert(ignore_permissions=True)


def test_budget_computes_cost_and_vacancy(site):
    d, g = _base(); _emp("E1", d, g)
    b = _budget(d, g, head=3)
    assert b.total_budgeted_headcount == 3 and b.total_filled == 1 and b.total_vacant == 2
    assert float(b.total_annual_cost) == 3 * 500000 * 12


def test_requisition_must_fit_the_approved_budget(site):
    d, g = _base(); _emp("E1", d, g); _budget(d, g, head=3)
    _req(d, g, 1)
    with pytest.raises(ValidationError, match="remain in the approved staff budget"):
        _req(d, g, 2)          # 3 budgeted - 1 employed - 1 already requested = 1 left
    r = _req(d, g, 1)
    assert r.budget_reference


def test_hired_applications_release_their_commitment(site):
    d, g = _base(); _budget(d, g, head=2)
    r = _req(d, g, 2)
    c = new_doc("Candidate", candidate_name="C1", email="c1@x.com").insert(ignore_permissions=True)
    app = new_doc("Job Application", candidate=c.name, requisition=r.name, application_date=date(2026, 4, 1), application_stage="Offer").insert(ignore_permissions=True)
    o = new_doc("Job Offer", application=app.name, candidate=c.name, requisition=r.name, offer_date=date(2026, 5, 1), proposed_start_date=date(2026, 6, 1),
                employment_type="Permanent", approval_status="Approved", decision="Accepted").insert(ignore_permissions=True)
    app = get_doc("Job Application", app.name, ignore_permissions=True); app.offer = o.name; app.application_stage = "Hired"; app.save(ignore_permissions=True)
    _req(d, g, 1)               # one of the two positions has been hired, so one slot is free again


def test_enforcement_setting_requires_a_budget(site):
    d, g = _base()
    _req(d, g, 5)               # no budget and not enforced: allowed
    s = get_list("Recruitment Settings", fields=["name"], limit=1, ignore_permissions=True)
    doc = get_doc("Recruitment Settings", s[0]["name"], ignore_permissions=True) if s else new_doc("Recruitment Settings")
    doc.require_department_staff_budget = 1
    doc.save(ignore_permissions=True) if s else doc.insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="no approved staff budget"):
        _req(d, g, 1)


def test_overlapping_approved_budgets_are_refused(site):
    d, g = _base(); _budget(d, g)
    with pytest.raises(ValidationError, match="already approved"):
        _budget(d, g)


def test_staff_budget_report_and_workflow_template(site):
    from velora_erp.hr.report.staff_budget_vs_actual import staff_budget_vs_actual as rpt
    from velora_erp.hr.workflow_templates import templates
    d, g = _base(); _emp("E1", d, g); _budget(d, g, head=2, status="Approved")
    out = rpt.execute({"as_of": "2026-06-01"})
    assert out
    assert any(t["doctype"] == "Department Staff Budget" for t in templates())
