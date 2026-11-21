"""Leave, attendance, overtime, recruitment and appraisal rules found weak in the v2.78 review."""
from datetime import date, datetime, timedelta
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.setup import after_install

HR = Session(user="hr1", roles=frozenset({"HR Manager"}))
OWNER = Session(user="ada@x.com", roles=frozenset({"HR Manager"}))


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'hr.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _emp(code="E1", **kw):
    return new_doc("Employee", employee_code=code, employee_name=code, employee_type="Permanent", date_of_joining=date(2020, 1, 1), **kw).insert(ignore_permissions=True)


def _requisition():
    d = new_doc("Department", department_name="Ops", department_code="OPS").insert(ignore_permissions=True)
    return new_doc("Job Requisition", requisition_title="Analyst", department=d.name, vacancy_count=1, business_justification="Growth", requisition_status="Draft").insert(ignore_permissions=True)


def _leave_setup(emp, **lt):
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1, **lt).insert(ignore_permissions=True)
    a = new_doc("Leave Allocation", employee=emp.name, leave_type=t.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
                allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
    return t, a


def _leave(emp, t, a, d1, d2, status="Pending Approval"):
    return new_doc("Leave Application", employee=emp.name, leave_type=t.name, leave_allocation=a.name, from_date=d1, to_date=d2, workflow_status=status, reason="Rest")


def test_leave_overlap_balance_negative_and_self_approval(site):
    emp = _emp(user_account="ada@x.com")
    t, a = _leave_setup(emp)
    first = _leave(emp, t, a, date(2026, 3, 2), date(2026, 3, 6)).insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="overlaps"):
        _leave(emp, t, a, date(2026, 3, 4), date(2026, 3, 9)).insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="Insufficient"):
        _leave(emp, t, a, date(2026, 4, 6), date(2026, 4, 17)).insert(ignore_permissions=True)
    # who may decide is the GUI workflow's job (see test_hr_workflow_gui_v283)
    first.workflow_status = "Approved"
    with session_as(HR):
        first.save(ignore_permissions=True)
    # completed leave still blocks an overlapping request
    done = get_doc("Leave Application", first.name, ignore_permissions=True)
    done.workflow_status = "Completed"
    with session_as(HR):
        done.save(ignore_permissions=True)
    with pytest.raises(ValidationError, match="overlaps"):
        _leave(emp, t, a, date(2026, 3, 2), date(2026, 3, 2)).insert(ignore_permissions=True)
    # a leave type that allows a negative balance may overdraw
    t2 = new_doc("Leave Type", leave_type_name="Advance", leave_category="Other", is_paid=1, allow_negative_balance=1).insert(ignore_permissions=True)
    a2 = new_doc("Leave Allocation", employee=emp.name, leave_type=t2.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31),
                 allocated_days=1, allocation_status="Approved").insert(ignore_permissions=True)
    _leave(emp, t2, a2, date(2026, 5, 4), date(2026, 5, 8)).insert(ignore_permissions=True)


def test_leave_before_joining_and_for_a_departed_employee(site):
    emp = _emp()
    t, a = _leave_setup(emp)
    with pytest.raises(ValidationError, match="joining date"):
        _leave(emp, t, a, date(2019, 12, 2), date(2019, 12, 3)).insert(ignore_permissions=True)
    emp = get_doc("Employee", emp.name, ignore_permissions=True)
    emp.employment_status = "Left"; emp.relieving_date = date(2026, 2, 1); emp.save(ignore_permissions=True)
    with pytest.raises(ValidationError, match="status is Left"):
        _leave(emp, t, a, date(2026, 3, 2), date(2026, 3, 3)).insert(ignore_permissions=True)


def test_attendance_and_overtime_rules(site):
    emp = _emp(user_account="ada@x.com")
    t, a = _leave_setup(emp)
    lv = _leave(emp, t, a, date(2026, 3, 2), date(2026, 3, 3)).insert(ignore_permissions=True)
    lv.workflow_status = "Approved"
    with session_as(HR):
        lv.save(ignore_permissions=True)
    with pytest.raises(ValidationError, match="approved leave"):
        new_doc("Attendance", employee=emp.name, attendance_date=date(2026, 3, 2), status="Present").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="future"):
        new_doc("Attendance", employee=emp.name, attendance_date=date.today() + timedelta(days=3), status="Present").insert(ignore_permissions=True)
    att = new_doc("Attendance", employee=emp.name, attendance_date=date(2026, 3, 4), status="Present").insert(ignore_permissions=True)
    att.approval_status = "Approved"

    day = datetime(2026, 3, 4, 18, 0)
    ot = new_doc("Overtime Request", employee=emp.name, overtime_date=date(2026, 3, 4), start_time=day, end_time=day + timedelta(hours=2), overtime_type="Weekday", reason="Month end").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="overlaps"):
        new_doc("Overtime Request", employee=emp.name, overtime_date=date(2026, 3, 4), start_time=day + timedelta(hours=1), end_time=day + timedelta(hours=3), overtime_type="Weekday", reason="Month end").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="overtime date"):
        new_doc("Overtime Request", employee=emp.name, overtime_date=date(2026, 3, 5), start_time=day, end_time=day + timedelta(hours=1), overtime_type="Weekday", reason="Month end").insert(ignore_permissions=True)
    ot.approval_status = "Approved"


def test_recruitment_rules(site):
    cand = new_doc("Candidate", candidate_name="Tola", email="t@x.com").insert(ignore_permissions=True)
    req = _requisition()
    app = new_doc("Job Application", candidate=cand.name, requisition=req.name, application_date=date.today(), application_stage="Applied").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="start date"):
        new_doc("Job Offer", application=app.name, candidate=cand.name, requisition=req.name, employment_type="Permanent", offer_date=date(2026, 1, 10), proposed_start_date=date(2026, 1, 5), gross_compensation=1000).insert(ignore_permissions=True)
    offer = new_doc("Job Offer", application=app.name, candidate=cand.name, requisition=req.name, employment_type="Permanent", offer_date=date(2026, 1, 10), proposed_start_date=date(2026, 2, 1),
                    gross_compensation=1000, offer_expiry_date=date(2026, 1, 20)).insert(ignore_permissions=True)
    offer.approval_status = "Approved"; offer.decision = "Accepted"
    with session_as(HR):
        with pytest.raises(ValidationError, match="expired"):
            offer.save(ignore_permissions=True)
    app = get_doc("Job Application", app.name, ignore_permissions=True)
    app.application_stage = "Hired"; app.offer = offer.name
    with pytest.raises(ValidationError, match="accepted"):
        app.save(ignore_permissions=True)

    start = datetime(2026, 6, 1, 10, 0)
    new_doc("Interview", application=app.name, interview_round="R1", interviewer="Zed", scheduled_start=start, scheduled_end=start + timedelta(hours=1), interview_status="Scheduled").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="already booked"):
        new_doc("Interview", application=app.name, interview_round="R2", interviewer="Zed", scheduled_start=start + timedelta(minutes=30), scheduled_end=start + timedelta(hours=2), interview_status="Scheduled").insert(ignore_permissions=True)
