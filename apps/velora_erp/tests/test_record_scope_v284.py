"""Record scope (v2.84): an employee sees their own records, a department manager sees their staff's, HR and System Manager see all."""
from datetime import date
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import PermissionDenied, DoesNotExistError
from velora.permissions import Session, session_as
from velora_erp.setup import after_install


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'sc.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def _emp(code, user, dept=None, reports_to=None):
    kw = {"department": dept} if dept else {}
    if reports_to: kw["reports_to"] = reports_to
    return new_doc("Employee", employee_code=code, employee_name=code, employee_type="Permanent", date_of_joining=date(2020, 1, 1), user_account=user, **kw).insert(ignore_permissions=True)


@pytest.fixture()
def org(site):
    d1 = new_doc("Department", department_code="D1", department_name="Sales").insert(ignore_permissions=True)
    d1b = new_doc("Department", department_code="D1B", department_name="Sales North", parent_department=d1.name).insert(ignore_permissions=True)
    d2 = new_doc("Department", department_code="D2", department_name="Ops").insert(ignore_permissions=True)
    mgr = _emp("M", "m@x.test", d1.name)
    d1.department_head = mgr.name; d1.save(ignore_permissions=True)
    a = _emp("A", "a@x.test", d1.name); b = _emp("B", "b@x.test", d1b.name); c = _emp("C", "c@x.test", d2.name)
    lt = new_doc("Leave Type", leave_type_name="Annual", leave_category="Annual", is_paid=1).insert(ignore_permissions=True)
    leaves = {}
    for e in (mgr, a, b, c):
        al = new_doc("Leave Allocation", employee=e.name, leave_type=lt.name, period_start=date(2026, 1, 1), period_end=date(2026, 12, 31), allocated_days=10, allocation_status="Approved").insert(ignore_permissions=True)
        leaves[e.name] = new_doc("Leave Application", employee=e.name, leave_type=lt.name, leave_allocation=al.name, from_date=date(2026, 3, 2), to_date=date(2026, 3, 3), reason="Rest").insert(ignore_permissions=True)
    return dict(mgr=mgr, a=a, b=b, c=c, d1=d1, leaves=leaves, lt=lt)


def _names(doctype, session, **kw):
    with session_as(session):
        return {r["name"] for r in get_list(doctype, fields=["name"], limit=1000, **kw)}


EMPLOYEE = lambda user: Session(user=user, roles=frozenset({"Employee"}))
MANAGER = Session(user="m@x.test", roles=frozenset({"Employee", "Department Manager"}))


def test_an_employee_sees_only_their_own_records(org):
    L = org["leaves"]
    assert _names("Leave Application", EMPLOYEE("a@x.test")) == {L[org["a"].name].name}
    assert _names("Leave Allocation", EMPLOYEE("c@x.test")) and len(_names("Leave Allocation", EMPLOYEE("c@x.test"))) == 1
    assert _names("Employee", EMPLOYEE("a@x.test")) == {org["a"].name}
    with session_as(EMPLOYEE("a@x.test")):
        with pytest.raises(DoesNotExistError):
            get_doc("Leave Application", L[org["c"].name].name)
        with pytest.raises(DoesNotExistError):
            get_doc("Employee", org["c"].name)


def test_an_employee_cannot_file_or_change_a_request_for_someone_else(org):
    with session_as(EMPLOYEE("a@x.test")):
        own = new_doc("Leave Application", employee=org["a"].name, leave_type=org["lt"].name, from_date=date(2026, 4, 6), to_date=date(2026, 4, 6), reason="Appointment").insert()
        assert own.name
        with pytest.raises(PermissionDenied):
            new_doc("Leave Application", employee=org["c"].name, leave_type=org["lt"].name, from_date=date(2026, 4, 7), to_date=date(2026, 4, 7), reason="x").insert()


def test_an_employee_cannot_approve_their_own_request_by_typing_the_status(org):
    with session_as(EMPLOYEE("a@x.test")):
        la = get_doc("Leave Application", org["leaves"][org["a"].name].name)
        la.workflow_status = "Approved"
        with pytest.raises(PermissionDenied):
            la.save()


def test_a_department_manager_sees_their_staff_including_sub_departments_and_not_others(org):
    L = org["leaves"]
    seen = _names("Leave Application", MANAGER)
    assert seen == {L[org["mgr"].name].name, L[org["a"].name].name, L[org["b"].name].name}
    assert L[org["c"].name].name not in seen
    assert _names("Employee", MANAGER) == {org["mgr"].name, org["a"].name, org["b"].name}
    with session_as(MANAGER):
        with pytest.raises(DoesNotExistError):
            get_doc("Leave Application", L[org["c"].name].name)


def test_direct_reports_are_staff_even_in_another_department(org):
    d = _emp("R", "r@x.test", None, reports_to=org["mgr"].name)
    assert d.name in _names("Employee", MANAGER)


def test_hr_manager_and_system_manager_see_everyone(org):
    for roles in ({"HR Manager"}, {"System Manager"}, {"HR Officer"}):
        assert len(_names("Leave Application", Session(user="h@x.test", roles=frozenset(roles)))) == 4


def test_access_is_the_union_of_a_persons_roles(org):
    """An HR Manager who is also an Employee is not narrowed to their own records."""
    both = Session(user="a@x.test", roles=frozenset({"Employee", "HR Manager"}))
    assert len(_names("Leave Application", both)) == 4


def test_a_person_with_no_employee_record_sees_nothing_and_a_manager_with_no_staff_sees_only_themselves(org):
    assert _names("Leave Application", EMPLOYEE("nobody@x.test")) == set()
    lone = _emp("Z", "z@x.test", org["d1"].name)   # in the manager's department, heads nothing
    assert _names("Leave Application", Session(user="z@x.test", roles=frozenset({"Employee", "Department Manager"}))) == set()


def test_a_department_manager_does_not_see_personal_identity_data_of_staff(org):
    with session_as(MANAGER):
        row = get_doc("Employee", org["a"].name).as_dict()
    assert "national_id_number" not in row or not row.get("national_id_number")
    assert "bank_account_no" not in row or not row.get("bank_account_no")


def test_an_unknown_scope_fails_closed(org):
    from velora.permissions import _scope_values
    with pytest.raises(PermissionDenied):
        _scope_values("typo_scope", EMPLOYEE("a@x.test"))
