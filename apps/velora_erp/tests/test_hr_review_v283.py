"""HR review (v2.83): balances that stay current, decisions that keep their approver, confidential cases, and an Employee record that follows its separation."""
from datetime import date, datetime
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.meta.registry import registry
from velora.permissions import Session, session_as, has_permission
from velora_erp.setup import after_install

HRM = Session(user="hrm", roles=frozenset({"HR Manager"}))
HRM2 = Session(user="hrm2", roles=frozenset({"HR Manager"}))
OFFICER = Session(user="officer", roles=frozenset({"HR Officer"}))


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'hr.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _emp(code="E1", **kw):
    return new_doc("Employee", employee_code=code, employee_name=code, employee_type="Permanent", date_of_joining=date(2020, 1, 1), **kw).insert(ignore_permissions=True)


def _setup(emp):
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1).insert(ignore_permissions=True)
    a = new_doc("Leave Allocation", employee=emp.name, leave_type=t.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
    return t, a


def _leave(e, t, a, d1=date(2026, 3, 2), d2=date(2026, 3, 6), status="Pending Approval"):
    return new_doc("Leave Application", employee=e.name, leave_type=t.name, leave_allocation=a.name, from_date=d1, to_date=d2, workflow_status=status, reason="Rest").insert(ignore_permissions=True)


def _alloc(a):
    d = get_doc("Leave Allocation", a.name, ignore_permissions=True)
    return float(d.used_days), float(d.pending_days), float(d.available_days)


def test_allocation_balances_follow_every_leave_application(site):
    e = _emp(); t, a = _setup(e)
    assert _alloc(a) == (0, 0, 10)
    la = _leave(e, t, a)
    assert _alloc(a) == (0, 5, 5), "a pending request reserves its days on the stored balance (the Leave Balance report reads it)"
    with session_as(HRM):
        la.workflow_status = "Cancelled"; la.save(ignore_permissions=True)
    assert _alloc(a) == (0, 0, 10), "cancelling gives the days back"
    la2 = _leave(e, t, a, date(2026, 1, 5), date(2026, 1, 9))
    with session_as(HRM):
        la2.workflow_status = "Approved"; la2.save(ignore_permissions=True)
        la2 = get_doc("Leave Application", la2.name, ignore_permissions=True); la2.workflow_status = "Completed"; la2.save(ignore_permissions=True)
    assert _alloc(a) == (5, 0, 5)


def test_an_approved_leave_can_be_annotated_but_not_re_dated_and_keeps_its_approver(site):
    e = _emp(); t, a = _setup(e)
    la = _leave(e, t, a)
    with session_as(HRM):
        la.workflow_status = "Approved"; la.save(ignore_permissions=True)
    with session_as(HRM2):
        la = get_doc("Leave Application", la.name, ignore_permissions=True); la.reason = "Rest (clarified)"; la.save(ignore_permissions=True)
        la = get_doc("Leave Application", la.name, ignore_permissions=True)
        assert la.approved_by == "hrm", "a later save by someone else does not replace the approver"
        la.to_date = date(2026, 3, 13)
        with pytest.raises(ValidationError, match="cannot be changed"):
            la.save(ignore_permissions=True)


def test_leave_uses_the_open_leave_periods_holiday_list(site):
    from velora import get_list
    e = _emp(); t, a = _setup(e)
    h = new_doc("Holiday List", holiday_list_name="2026", year=2026, holiday_dates=["2026-03-04"]).insert(ignore_permissions=True)
    new_doc("Leave Period", period_code="LP26", period_name="2026", from_date=date(2026, 1, 1), to_date=date(2026, 12, 31), period_status="Draft", holiday_list=h.name).insert(ignore_permissions=True)
    lp = get_list("Leave Period", fields=["name"], limit=1, ignore_permissions=True)[0]["name"]
    with session_as(HRM):
        doc = get_doc("Leave Period", lp, ignore_permissions=True); doc.period_status = "Open"; doc.save(ignore_permissions=True)
    la = _leave(e, t, a)
    assert la.total_days == 4, "Mon-Fri less the 4 March holiday"


@pytest.mark.parametrize("dt", ["Career Development Plan", "Critical Position", "Succession Candidate", "Performance Cycle Assignment"])
def test_hr_manager_can_use_every_hr_record_type(site, dt):
    with session_as(HRM):
        for p in ("read", "write", "create"):
            assert has_permission(registry.get(dt), p), (dt, p)


def test_hr_manager_can_submit_a_bulk_leave_policy_assignment(site):
    with session_as(HRM):
        assert has_permission(registry.get("Leave Policy Assignment"), "submit")


def test_grievance_cases_are_not_visible_to_hr_officers(site):
    meta = registry.get("Employee Relations Case")
    with session_as(OFFICER):
        assert not has_permission(meta, "read")
    with session_as(HRM):
        assert has_permission(meta, "read")


def test_a_closed_separation_makes_the_employee_a_leaver(site):
    e = _emp()
    s = new_doc("Employee Separation", employee=e.name, separation_type="Resignation", notice_date=date(2026, 5, 1), last_working_date=date(2026, 5, 31), reason="Relocating",
                clearance_items=[{"clearance_area": "IT", "clearance_status": "Pending"}])
    with session_as(HRM):
        s.insert(ignore_permissions=True)
        s.approval_status = "Approved"; s.workflow_status = "Approved"; s.save(ignore_permissions=True)
    assert get_doc("Employee", e.name, ignore_permissions=True).employment_status == "Notice Period"
    with session_as(HRM):
        s = get_doc("Employee Separation", s.name, ignore_permissions=True)
        s.clearance_items[0].clearance_status = "Cleared"; s.workflow_status = "Cleared"; s.save(ignore_permissions=True)
        s = get_doc("Employee Separation", s.name, ignore_permissions=True)
        s.workflow_status = "Closed"; s.final_settlement_status = "Completed"; s.finance_reference = "FS-1"; s.save(ignore_permissions=True)
    e = get_doc("Employee", e.name, ignore_permissions=True)
    assert e.employment_status == "Left" and e.disabled and str(e.relieving_date)[:10] == "2026-05-31"


def test_an_approved_confirmation_confirms_the_employee(site):
    e = _emp(employment_status="Probation")
    r = new_doc("Probation Review", employee=e.name, due_date=date(2026, 6, 1), review_date=date(2026, 6, 2), review_stage="Final", recommendation="Confirm", approval_status="Draft")
    with session_as(HRM):
        r.insert(ignore_permissions=True)
        r.approval_status = "Approved"; r.save(ignore_permissions=True)
    e = get_doc("Employee", e.name, ignore_permissions=True)
    assert e.employment_status == "Active" and str(e.date_of_confirmation)[:10] == "2026-06-02"


def test_overtime_cannot_be_changed_after_payroll_has_reviewed_it(site):
    e = _emp()
    ot = new_doc("Overtime Request", employee=e.name, overtime_date=date(2026, 3, 2), start_time=datetime(2026, 3, 2, 18), end_time=datetime(2026, 3, 2, 20), overtime_type="Weekday", reason="Month end", approval_status="Draft").insert(ignore_permissions=True)
    ot = get_doc("Overtime Request", ot.name, ignore_permissions=True)
    ot.end_time = datetime(2026, 3, 2, 21); ot.save(ignore_permissions=True)          # still changeable while unreviewed
    from velora_erp.finance.doctype._utils import db_update
    db_update(ot, payroll_review_status="Accepted as Payroll Input")
    ot = get_doc("Overtime Request", ot.name, ignore_permissions=True)
    ot.end_time = datetime(2026, 3, 2, 23)
    with pytest.raises(ValidationError, match="reviewed for payroll"):
        ot.save(ignore_permissions=True)


def test_reconciling_punches_does_not_stop_at_an_employee_on_approved_leave(site):
    from velora_erp.hr.attendance_integrations import ingest_events, reconcile_punches
    e1, e2 = _emp("E1"), _emp("E2")
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1).insert(ignore_permissions=True)
    a = new_doc("Leave Allocation", employee=e1.name, leave_type=t.name, period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
    la = new_doc("Leave Application", employee=e1.name, leave_type=t.name, leave_allocation=a.name, from_date=date(2025, 3, 3), to_date=date(2025, 3, 3), workflow_status="Pending Approval", reason="r")
    la.insert(ignore_permissions=True)
    with session_as(HRM):
        la.workflow_status = "Approved"; la.save(ignore_permissions=True)
    integ = new_doc("Attendance Integration", integration_code="GATE", integration_name="Gate", provider="Generic REST API", transport="Normalised Event Push", active=1, timezone="Africa/Lagos").insert(ignore_permissions=True)
    for emp, uid in ((e1, "1"), (e2, "2")):
        new_doc("Attendance Device User Mapping", mapping_key=f"gate-{uid}", integration=integ.name, external_user_id=uid, employee=emp.name, active=1).insert(ignore_permissions=True)
    events = [{"external_user_id": u, "timestamp": f"2025-03-03 {h}", "event_id": f"{u}-{h}"} for u in ("1", "2") for h in ("08:00:00", "17:00:00")]
    assert ingest_events(integ.name, events)["created"] == 4
    result = reconcile_punches(integ.name)
    assert result["attendance_created"] == 1 and result["needs_review"] == 1
