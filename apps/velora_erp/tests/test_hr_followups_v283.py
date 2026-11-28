from datetime import date
import pytest, velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora_erp.setup import after_install


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'fu.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _emp(code, **kw):
    return new_doc("Employee", employee_code=code, employee_name=code, employee_type="Permanent", date_of_joining=date(2020, 1, 1), **kw).insert(ignore_permissions=True)


def test_active_leave_policy_can_be_resaved_unchanged_but_not_edited(site):
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1).insert(ignore_permissions=True)
    p = new_doc("Leave Policy", policy_code="LP1", policy_name="Std", policy_version=1, effective_from=date(2026, 1, 1), status="Active",
                entitlements=[{"leave_type": t.name, "annual_entitlement_days": 20}]).insert(ignore_permissions=True)
    p = get_doc("Leave Policy", p.name, ignore_permissions=True); p.save(ignore_permissions=True)          # nothing changed
    p = get_doc("Leave Policy", p.name, ignore_permissions=True); p.entitlements[0].annual_entitlement_days = 30
    with pytest.raises(ValidationError, match="immutable"):
        p.save(ignore_permissions=True)
    p = get_doc("Leave Policy", p.name, ignore_permissions=True); p.policy_name = "Renamed"
    with pytest.raises(ValidationError, match="immutable"):
        p.save(ignore_permissions=True)


def test_morning_and_afternoon_half_days_on_one_date_do_not_clash(site):
    e = _emp("E1")
    t = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1, allow_half_day=1).insert(ignore_permissions=True)
    a = new_doc("Leave Allocation", employee=e.name, leave_type=t.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
    mk = lambda part: new_doc("Leave Application", employee=e.name, leave_type=t.name, leave_allocation=a.name, from_date=date(2026, 3, 2), to_date=date(2026, 3, 2),
                              half_day=1, half_day_period=part, workflow_status="Pending Approval", reason="Errand")
    mk("First Half").insert(ignore_permissions=True)
    mk("Second Half").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="overlaps"):
        mk("First Half").insert(ignore_permissions=True)


def test_an_approved_primary_reporting_assignment_sets_the_employees_manager(site):
    d = new_doc("Department", department_code="OPS", department_name="Ops").insert(ignore_permissions=True)
    boss, staff = _emp("B1"), _emp("S1")
    new_doc("Reporting Assignment", employee=staff.name, department=d.name, reports_to=boss.name, is_primary=1,
            effective_from=date(2026, 1, 1), assignment_status="Approved").insert(ignore_permissions=True)
    assert get_doc("Employee", staff.name, ignore_permissions=True).reports_to == boss.name
