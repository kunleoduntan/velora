"""Leave policy eligibility, versioning and bulk allocation regression tests."""
import json, sys
from pathlib import Path
from types import SimpleNamespace
import pytest

PROJECT = Path(__file__).resolve().parents[1]
APP = str(PROJECT / "apps" / "velora_erp")
if APP not in sys.path:
    sys.path.insert(0, APP)


def registry():
    from velora.meta.registry import Registry
    r = Registry(); r.load(["velora_erp"]); return r


def test_leave_policy_engine_doctypes_register():
    r = registry()
    expected = {"Leave Period", "Leave Policy", "Leave Policy Entitlement", "Leave Policy Eligibility Rule",
                "Leave Policy Assignment", "Leave Policy Selected Employee", "Employee Category Row",
                "Employee Classification Category", "Employee Classification Value"}
    assert expected.issubset(set(r._doctypes))
    assert r._doctypes["Leave Allocation"].get_field("leave_policy_assignment")


def test_employee_supports_multiple_effective_dated_categories():
    r = registry()
    employee = r._doctypes["Employee"]
    assert employee.get_field("categories").options == "Employee Category Row"
    row = r._doctypes["Employee Category Row"]
    assert row.istable
    assert row.get_field("category_name").options == "Employee Classification Category"
    assert row.get_field("category_value").options == "Employee Classification Value"


def test_eligibility_rules_use_and_within_group_or_between_groups():
    from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import employee_matches_eligibility
    context = {"gender": "Female", "department": "Finance", "categories": [
        {"category_name": "Management Level", "category_value": "Manager"},
        {"category_name": "Employment Track", "category_value": "Professional"},
    ]}
    rules = [
        {"rule_group": 1, "field_name": "Gender", "operator": "Equals", "value": "Female"},
        {"rule_group": 1, "field_name": "Department", "operator": "Equals", "value": "Finance"},
        {"rule_group": 2, "field_name": "Employee Category", "category_name": "Management Level", "category_value": "Manager", "operator": "Equals"},
    ]
    assert employee_matches_eligibility(context, rules)
    rules.append({"rule_group": 1, "field_name": "Employee Category", "category_name": "Employment Track", "category_value": "Non-Professional", "operator": "Equals"})
    assert employee_matches_eligibility(context, rules)  # OR group 2 still matches
    assert not employee_matches_eligibility(context, [
        {"rule_group": 1, "field_name": "Gender", "operator": "Equals", "value": "Male"},
        {"rule_group": 1, "field_name": "Department", "operator": "Equals", "value": "Finance"},
        {"rule_group": 2, "field_name": "Employee Category", "category_name": "Management Level", "category_value": "Executive", "operator": "Equals"}
    ])


def test_eligibility_supports_not_in_and_unset():
    from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import employee_matches_eligibility
    context = {"employee_type": "Contract", "gender": None, "categories": []}
    assert employee_matches_eligibility(context, [
        {"rule_group": 1, "field_name": "Employee Type", "operator": "Not In", "value": "Temporary;Intern"},
        {"rule_group": 1, "field_name": "Gender", "operator": "Is Not Set", "value": ""},
    ])


def test_policy_proration_methods():
    from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import _prorated_days
    employee = SimpleNamespace(date_of_joining="2026-04-15")
    start, end = __import__('datetime').date(2026, 1, 1), __import__('datetime').date(2026, 12, 31)
    assert _prorated_days(24, "Full Entitlement", employee, start, end) == 24
    assert _prorated_days(24, "Calendar Days", employee, start, end) == 17.16
    assert _prorated_days(24, "Completed Months", employee, start, end) == 16
    late_hire = SimpleNamespace(date_of_joining="2026-12-15")
    assert _prorated_days(24, "Completed Months", late_hire, start, end) == 0


def test_bulk_policy_assignment_generates_each_leave_type_and_skips_existing(monkeypatch):
    import velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment as mod
    employee = SimpleNamespace(name="EMP-001")
    policy = SimpleNamespace(policy_code="GENERAL", policy_version=2, entitlements=[
        {"leave_type":"Annual", "annual_entitlement_days":20, "proration_method":"Full Entitlement"},
        {"leave_type":"Sick", "annual_entitlement_days":10, "proration_method":"Full Entitlement"},
    ])
    monkeypatch.setattr(mod, "get_doc", lambda *a, **k: policy)
    monkeypatch.setattr(mod, "_eligible_employees", lambda *a, **k: [employee])
    monkeypatch.setattr(mod, "get_list", lambda doctype, **kwargs: ([{"name":"OLD-ALLOC","employee":"EMP-001","leave_type":"Annual","period_start":"2026-01-01","period_end":"2026-12-31","allocation_status":"Approved","available_days":0}] if doctype=="Leave Allocation" else []))
    created=[]
    class FakeAllocation:
        def __init__(self, **kwargs): self.__dict__.update(kwargs); self.name="ALLOC-NEW"
        def insert(self, **kwargs): created.append(self); return self
    monkeypatch.setattr(mod, "new_doc", lambda doctype, **kwargs: FakeAllocation(**kwargs))
    updates=[]; monkeypatch.setattr(mod, "db_update", lambda doc, **kwargs: updates.append(kwargs))
    doc=mod.LeavePolicyAssignment.__new__(mod.LeavePolicyAssignment)
    doc.name="BULK-001"; doc.policy="GENERAL"; doc.assignment_date="2026-01-01"
    doc.period_start="2026-01-01"; doc.period_end="2026-12-31"; doc.selection_mode="All Eligible Employees"
    doc.selected_employees=[]; doc.override_eligibility=0
    doc.on_submit()
    assert len(created)==1 and created[0].leave_type=="Sick"
    assert updates[-1]["generated_allocation_count"]==1
    assert updates[-1]["skipped_allocation_count"]==1
    assert updates[-1]["assignment_status"]=="Completed with Exceptions"
    assert json.loads(updates[-1]["result_details"])[0]["result"].startswith("Skipped")


def test_eligibility_can_evaluate_attributes_at_assignment_or_leave_period_start():
    from velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment import employee_matches_eligibility
    context = {"_by_date": {
        "Assignment Date": {"department": "Operations"},
        "Leave Period Start": {"department": "Finance"},
    }}
    assert employee_matches_eligibility(context, [
        {"rule_group": 1, "field_name": "Department", "operator": "Equals", "value": "Finance", "effective_on": "Leave Period Start"}
    ])
    assert employee_matches_eligibility(context, [
        {"rule_group": 1, "field_name": "Department", "operator": "Equals", "value": "Operations", "effective_on": "Assignment Date"}
    ])
    assert not employee_matches_eligibility(context, [
        {"rule_group": 1, "field_name": "Department", "operator": "Equals", "value": "Operations", "effective_on": "Leave Period Start"}
    ])


def test_carry_forward_is_capped_by_policy_entitlement(monkeypatch):
    import velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment as mod
    monkeypatch.setattr(mod, "get_list", lambda *a, **k: [
        {"name":"OLD-1", "employee":"EMP-001", "leave_type":"Annual", "period_end":"2025-12-31", "available_days":7.5},
        {"name":"FUTURE", "employee":"EMP-001", "leave_type":"Annual", "period_end":"2027-12-31", "available_days":99},
    ])
    employee=SimpleNamespace(name="EMP-001")
    assert mod._carry_forward_balance(employee, "Annual", __import__('datetime').date(2026,1,1),
        {"allow_carry_forward":1, "maximum_carry_forward_days":5}) == 5
    assert mod._carry_forward_balance(employee, "Annual", __import__('datetime').date(2026,1,1),
        {"allow_carry_forward":0, "maximum_carry_forward_days":5}) == 0


def test_leave_period_master_is_registered_and_controls_assignment_period():
    r = registry()
    assert r._doctypes["Leave Period"].get_field("from_date")
    assert r._doctypes["Leave Policy Assignment"].get_field("leave_period").options == "Leave Period"
    assert r._doctypes["Leave Policy Assignment"].get_field("period_start").read_only


def test_leave_period_rejects_overlapping_periods_for_same_entity(monkeypatch):
    import velora_erp.hr.doctype.leave_period.leave_period as mod
    monkeypatch.setattr(mod, "get_session", lambda: SimpleNamespace(user="hr@example.com", roles=["HR Manager"]))
    monkeypatch.setattr(mod, "get_list", lambda *a, **k: [
        {"name":"FY26", "company":"Velora Nigeria Ltd", "from_date":"2026-01-01", "to_date":"2026-12-31"}
    ])
    doc=mod.LeavePeriod.__new__(mod.LeavePeriod)
    doc.name="FY27-OVERLAP"; doc.period_code="FY27"; doc.period_name="FY 2027"
    doc.company="Velora Nigeria Ltd"; doc.from_date="2026-12-01"; doc.to_date="2027-11-30"
    doc.period_status="Open"
    with pytest.raises(Exception): doc.validate()


def test_policy_assignment_uses_open_leave_period_and_populates_allocation_dates(monkeypatch):
    import velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment as mod
    policy=SimpleNamespace(status="Active", effective_from="2026-01-01", effective_to="2026-12-31", company="", eligibility_rules=[])
    period=SimpleNamespace(period_status="Open", from_date="2026-01-01", to_date="2026-12-31", company="")
    monkeypatch.setattr(mod, "get_doc", lambda doctype, *a, **k: policy if doctype=="Leave Policy" else period)
    monkeypatch.setattr(mod, "_eligible_employees", lambda *a, **k: [SimpleNamespace(name="EMP-001")])
    doc=mod.LeavePolicyAssignment.__new__(mod.LeavePolicyAssignment)
    doc.policy="GENERAL"; doc.assignment_date="2026-01-05"; doc.leave_period="FY26"
    doc.period_start=None; doc.period_end=None; doc.selection_mode="All Eligible Employees"
    doc.selected_employees=[]; doc.override_eligibility=0
    doc.validate()
    assert str(doc.period_start)=="2026-01-01"
    assert str(doc.period_end)=="2026-12-31"
    assert doc.preview_employee_count==1


def test_policy_assignment_rejects_closed_leave_period(monkeypatch):
    import velora_erp.hr.doctype.leave_policy_assignment.leave_policy_assignment as mod
    period=SimpleNamespace(period_status="Closed", from_date="2026-01-01", to_date="2026-12-31", company="")
    monkeypatch.setattr(mod, "get_doc", lambda *a, **k: period)
    doc=mod.LeavePolicyAssignment.__new__(mod.LeavePolicyAssignment)
    doc.policy="GENERAL"; doc.assignment_date="2026-01-05"; doc.leave_period="FY26"
    doc.period_start=None; doc.period_end=None; doc.selection_mode="All Eligible Employees"
    doc.selected_employees=[]; doc.override_eligibility=0
    with pytest.raises(Exception): doc.validate()


def test_classification_values_are_unique_within_category(monkeypatch):
    import velora_erp.hr.doctype.employee_classification_value.employee_classification_value as mod
    monkeypatch.setattr(mod, "get_doc", lambda *a, **k: SimpleNamespace(disabled=0))
    monkeypatch.setattr(mod, "get_list", lambda *a, **k: [
        {"name":"MANAGER", "value_name":"Manager"},
        {"name":"EXECUTIVE", "value_name":"Executive"},
    ])
    doc=mod.EmployeeClassificationValue.__new__(mod.EmployeeClassificationValue)
    doc.name="MANAGER-NEW"; doc.value_code="MANAGER-NEW"; doc.value_name="manager"; doc.category="MGMT"
    with pytest.raises(Exception): doc.validate()
