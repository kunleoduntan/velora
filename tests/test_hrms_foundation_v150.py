"""Source metadata and compatibility tests for the HRMS foundation release."""
import json
import sys
from pathlib import Path


def _registry():
    project = Path(__file__).resolve().parents[1]
    app_path = str(project / "apps" / "velora_erp")
    if app_path not in sys.path:
        sys.path.insert(0, app_path)
    from velora.meta.registry import Registry
    registry = Registry()
    registry.load(["velora_erp", "velora_projectone"])
    return registry


def test_employee_is_single_canonical_hr_owned_doctype():
    registry = _registry()
    employee = registry._doctypes["Employee"]
    assert employee.module == "HR"
    assert employee.controller_module.endswith("hr.doctype.employee.employee")
    assert {"employee_code", "employee_name", "default_payable_account",
            "advance_account", "loan_account"}.issubset(set(employee.column_names()))


def test_hr_foundation_doctypes_and_links_load():
    registry = _registry()
    expected = {
        "Employee HR Profile", "Department", "Designation", "Job Grade",
        "Job Band", "Job Position", "Work Location", "Reporting Assignment",
    }
    assert expected.issubset(set(registry._doctypes))
    assert registry._doctypes["Employee HR Profile"].get_field("employee").options == "Employee"
    assert registry._doctypes["Reporting Assignment"].get_field("employee").options == "Employee"
    assert registry._doctypes["Reporting Assignment"].get_field("department").options == "Department"


def test_employee_hr_profile_is_restricted_to_hr_roles():
    registry = _registry()
    profile = registry._doctypes["Employee HR Profile"]
    roles = {p.role for p in profile.permissions if p.read}
    assert roles == {"System Manager", "HR Manager", "HR Officer"}


def test_employee_finance_read_access_is_retained_but_not_write():
    registry = _registry()
    employee = registry._doctypes["Employee"]
    perms = {p.role: p for p in employee.permissions if p.permlevel == 0}      # level 1 grants (Gross Pay) are separate rows
    assert perms["Finance Manager"].read is True
    assert perms["Finance Manager"].write is False
    assert perms["Accountant"].read is True
    assert perms["Accountant"].write is False
    for role in ("Payroll Manager", "Payroll Officer", "Employee Finance Officer"):
        assert perms[role].read is True
        assert perms[role].write is False


def test_all_hr_metadata_uses_supported_field_types():
    project = Path(__file__).resolve().parents[1]
    root = project / "apps" / "velora_erp" / "velora_erp" / "hr" / "doctype"
    supported = {"Data", "Text", "Int", "Float", "Currency", "Check", "Date",
                 "Datetime", "Select", "Link", "JSON", "Section Break",
                 "Column Break", "Tab Break", "Table"}
    for path in root.glob("*/*.json"):
        data = json.loads(path.read_text())
        assert data["module"] == "HR"
        assert all(field["fieldtype"] in supported for field in data["fields"])


def test_hr_workspace_is_registered_for_install_and_migration():
    project = Path(__file__).resolve().parents[1]
    setup = (project / "apps" / "velora_erp" / "velora_erp" / "setup.py").read_text()
    assert "def ensure_hr_workspace()" in setup
    assert setup.count("ensure_hr_workspace()") >= 3
