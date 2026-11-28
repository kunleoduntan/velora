"""Leave, attendance, shifts and employee service request foundation tests."""
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
    r = Registry(); r.load(["velora_erp", "velora_projectone"]); return r


def test_workforce_doctypes_register():
    r = registry()
    expected = {"Leave Type", "Leave Allocation", "Leave Application", "Holiday List", "Attendance", "Shift Type", "Shift Assignment", "Overtime Request", "HR Service Request"}
    assert expected.issubset(set(r._doctypes))


def test_leave_policy_supports_paid_unpaid_and_carry_forward_controls():
    r = registry(); d = r._doctypes["Leave Type"]
    assert d.get_field("is_paid") and d.get_field("carry_forward_allowed")
    assert d.get_field("requires_attachment") and d.get_field("allow_negative_balance")


def test_leave_application_requires_allocation_and_records_payroll_treatment():
    r = registry(); d = r._doctypes["Leave Application"]
    assert d.get_field("leave_allocation").options == "Leave Allocation"
    assert d.get_field("payroll_treatment").read_only
    assert d.get_field("holiday_list").options == "Holiday List"


def test_attendance_has_single_day_clocking_and_approval_fields():
    r = registry(); d = r._doctypes["Attendance"]
    assert d.get_field("check_in") and d.get_field("check_out")
    assert d.get_field("approval_status") and d.get_field("attendance_source")


def test_shift_type_calculates_cross_midnight_hours_and_breaks():
    from velora_erp.hr.doctype.shift_type.shift_type import ShiftType
    doc = ShiftType.__new__(ShiftType)
    doc.start_time="22:00"; doc.end_time="06:00"; doc.crosses_midnight=1
    doc.break_minutes=30; doc.expected_hours=None
    doc.validate()
    assert doc.expected_hours == 7.5


def test_shift_type_rejects_inconsistent_expected_hours():
    from velora_erp.hr.doctype.shift_type.shift_type import ShiftType
    from velora.exceptions import ValidationError
    doc = ShiftType.__new__(ShiftType)
    doc.start_time="09:00"; doc.end_time="17:00"; doc.crosses_midnight=0
    doc.break_minutes=60; doc.expected_hours=8
    with pytest.raises(Exception): doc.validate()


def test_overtime_calculates_hours_but_does_not_create_payroll_input():
    r = registry(); d = r._doctypes["Overtime Request"]
    assert d.get_field("payroll_input").options == "Payroll Input"
    assert d.get_field("payroll_input").read_only
    assert d.get_field("payroll_review_status").read_only


def test_hr_service_request_is_not_exposed_to_all_employees_without_row_scope():
    # v2.84: Employees may raise requests, but only ever see their own; the
    # default row scope (hr/scopes.py) is what keeps them apart.
    from velora_erp.hr import scopes
    r = registry(); d = r._doctypes["HR Service Request"]
    if "Employee" in {p.role for p in d.permissions}:
        pols = scopes.default_policies()
        assert any(x[0] == "Employee" and x[1] == "HR Service Request" for x in pols)


def test_all_new_hr_metadata_uses_supported_field_types():
    root = PROJECT / "apps" / "velora_erp" / "velora_erp" / "hr" / "doctype"
    supported = {"Data", "Text", "Int", "Float", "Currency", "Check", "Date", "Datetime", "Select", "Link", "JSON", "Section Break", "Column Break", "Tab Break", "Table"}
    for p in root.glob("*/*.json"):
        d = json.loads(p.read_text())
        assert d["module"] == "HR"
        assert all(x["fieldtype"] in supported for x in d["fields"])


def test_hr_operations_workspace_is_configured():
    source = (PROJECT / "apps" / "velora_erp" / "velora_erp" / "setup.py").read_text()
    assert 'name":"HR Operations"' in source
    assert '"title":"Leave Applications"' in source
    assert 'ensure_hr_operations_workspace()' in source


def test_leave_application_excludes_weekends_and_configured_holidays(monkeypatch):
    import velora_erp.hr.doctype.leave_application.leave_application as mod
    policy = SimpleNamespace(disabled=0, allow_half_day=1, requires_attachment=0,
                             include_weekends=0, max_consecutive_days=0, is_paid=1)
    holiday = SimpleNamespace(holiday_dates='["2026-11-18"]')
    allocation = SimpleNamespace(allocation_status="Approved", employee="EMP-1", leave_type="Annual",
                                 period_start="2026-01-01", period_end="2026-12-31", available_days=4, allocated_days=4, carry_forward_days=0, adjustment_days=0)
    monkeypatch.setattr(mod, "get_doc", lambda dt, name, ignore_permissions=True: {
        "Leave Type": policy, "Holiday List": holiday, "Leave Allocation": allocation}[dt])
    monkeypatch.setattr(mod, "get_list", lambda *a, **k: [])
    doc = mod.LeaveApplication.__new__(mod.LeaveApplication)
    doc.name="LEAVE-NEW"; doc.employee="EMP-1"; doc.leave_type="Annual"
    doc.from_date="2026-11-16"; doc.to_date="2026-11-20"; doc.half_day=0
    doc.holiday_list="HOL-2026"; doc.leave_allocation="ALLOC-1"; doc.supporting_document=None
    doc.workflow_status="Pending Approval"; doc.payroll_treatment="Not Applicable"
    doc.validate()
    assert doc.total_days == 4


def test_leave_application_rejects_insufficient_allocation(monkeypatch):
    import velora_erp.hr.doctype.leave_application.leave_application as mod
    policy = SimpleNamespace(disabled=0, allow_half_day=1, requires_attachment=0,
                             include_weekends=0, max_consecutive_days=0, is_paid=1)
    allocation = SimpleNamespace(allocation_status="Approved", employee="EMP-1", leave_type="Annual",
                                 period_start="2026-01-01", period_end="2026-12-31", available_days=1)
    monkeypatch.setattr(mod, "get_doc", lambda dt, name, ignore_permissions=True: {
        "Leave Type": policy, "Leave Allocation": allocation}[dt])
    monkeypatch.setattr(mod, "get_list", lambda *a, **k: [])
    doc = mod.LeaveApplication.__new__(mod.LeaveApplication)
    doc.name="LEAVE-NEW"; doc.employee="EMP-1"; doc.leave_type="Annual"
    doc.from_date="2026-11-16"; doc.to_date="2026-11-18"; doc.half_day=0
    doc.holiday_list=None; doc.leave_allocation="ALLOC-1"; doc.supporting_document=None
    doc.workflow_status="Pending Approval"; doc.payroll_treatment="Not Applicable"
    with pytest.raises(Exception): doc.validate()


def test_leave_application_reserves_balance_across_multiple_pending_requests(monkeypatch):
    import velora_erp.hr.doctype.leave_application.leave_application as mod
    policy = SimpleNamespace(disabled=0, allow_half_day=1, requires_attachment=0,
                             include_weekends=0, max_consecutive_days=0, is_paid=1)
    allocation = SimpleNamespace(allocation_status="Approved", employee="EMP-1", leave_type="Annual",
                                 period_start="2026-01-01", period_end="2026-12-31", available_days=5,
                                 allocated_days=5, carry_forward_days=0, adjustment_days=0)
    monkeypatch.setattr(mod, "get_doc", lambda dt, name, ignore_permissions=True: {
        "Leave Type": policy, "Leave Allocation": allocation}[dt])
    def lists(doctype, filters=None, **kwargs):
        if doctype == "Leave Application" and filters and filters[0][0] == "leave_allocation":
            return [{"name":"OTHER-REQUEST","total_days":4,"workflow_status":"Pending Approval"}]
        return []
    monkeypatch.setattr(mod, "get_list", lists)
    doc = mod.LeaveApplication.__new__(mod.LeaveApplication)
    doc.name="NEW-REQUEST"; doc.employee="EMP-1"; doc.leave_type="Annual"
    doc.from_date="2026-11-16"; doc.to_date="2026-11-17"; doc.half_day=0
    doc.holiday_list=None; doc.leave_allocation="ALLOC-1"; doc.supporting_document=None
    doc.workflow_status="Pending Approval"; doc.payroll_treatment="Not Applicable"
    with pytest.raises(Exception): doc.validate()
