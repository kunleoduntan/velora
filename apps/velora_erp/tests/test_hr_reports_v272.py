"""Every new HR report runs on an empty site and on seeded data, and totals/flags are right."""
from datetime import date, datetime, time, timedelta
import pytest
import velora
from velora import new_doc
from velora.reporting.runner import run_report
from velora_erp.setup import after_install

REPORTS = ["Employee Directory", "Headcount Analysis", "Leave Balance", "Leave Utilisation", "Attendance Summary", "Overtime Register",
           "Contract and Probation Watch", "Training Register", "Recruitment Pipeline", "Separation and Attrition",
           "Performance Rating Distribution", "Payroll Cost Analysis", "Statutory Deductions Summary", "Payroll Variance"]


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'hr.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield


def _data(result):
    return [r for r in result.rows if r.type == "data"]


def test_all_hr_reports_run_on_empty_site(site):
    for name in REPORTS:
        result = run_report(name, {})
        assert result.title == name


def test_directory_headcount_and_filters(site):
    new_doc("Branch", branch_code="LAG", branch_name="Lagos HQ").insert(ignore_permissions=True)
    for code, name, joined in (("E1", "Ada Obi", date(2020, 1, 6)), ("E2", "Bayo Ade", date.today() - timedelta(days=10))):
        new_doc("Employee", employee_code=code, first_name=name.split()[0], last_name=name.split()[1], branch="LAG", date_of_joining=joined, employee_type="Permanent").insert(ignore_permissions=True)
    rows = _data(run_report("Employee Directory", {"branch": "LAG"}))
    assert {r.values["employee_name"] for r in rows} == {"Ada OBI", "Bayo ADE"}
    assert all(r.values["tenure"] is not None for r in rows)
    head = run_report("Headcount Analysis", {"group_by": "Branch", "from_date": date.today() - timedelta(days=30), "to_date": date.today()})
    row = _data(head)[0].values
    assert row["joiners"] == 1 and row["closing"] == 2 and row["opening"] == 1
    # unknown filter value yields nothing, not an error
    assert _data(run_report("Employee Directory", {"branch": "LAG", "employee": "NOPE"})) == []


def test_branch_is_a_validated_link(site):
    with pytest.raises(Exception):
        new_doc("Employee", employee_code="E9", employee_name="No Branch", branch="DOES-NOT-EXIST").insert(ignore_permissions=True)


def test_employee_name_is_fetched_on_child_documents(site):
    new_doc("Employee", employee_code="E5", first_name="Chi", last_name="Eze").insert(ignore_permissions=True)
    ot = new_doc("Overtime Request", employee="E5", overtime_date=date.today(), overtime_type="Weekday", start_time=datetime.combine(date.today(), time(18)), end_time=datetime.combine(date.today(), time(20)), hours=2, approval_status="Approved", reason="Month-end close").insert(ignore_permissions=True)
    assert ot.employee_name == "Chi EZE"


def test_overtime_and_contract_watch_logic(site):
    new_doc("Employee", employee_code="E6", employee_name="Dayo Bello").insert(ignore_permissions=True)
    new_doc("Overtime Request", employee="E6", overtime_date=date.today(), overtime_type="Weekend", start_time=datetime.combine(date.today(), time(8)), end_time=datetime.combine(date.today(), time(12)), hours=4, approval_status="Approved", reason="Month-end close").insert(ignore_permissions=True)
    result = run_report("Overtime Register", {"employee": "E6"})
    assert [r.values["hours"] for r in _data(result)] == [4]
    assert [r for r in result.rows if r.type == "total"][0].values["hours"] == 4
    new_doc("Employment Contract", employee="E6", contract_reference="C-6", contract_type="Fixed Term", start_date=date.today() - timedelta(days=300),
            end_date=date.today() + timedelta(days=20), contract_status="Approved").insert(ignore_permissions=True)
    rows = _data(run_report("Contract and Probation Watch", {"within_days": 30}))
    assert [r.values["flag"] for r in rows] == ["Due within 30 days"]
    assert _data(run_report("Contract and Probation Watch", {"within_days": 5})) == []
