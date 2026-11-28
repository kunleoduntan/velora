from datetime import date
import pytest

from velora import new_doc
from velora.exceptions import ValidationError
from test_finance_reporting import setup_finance, teardown


def _jurisdiction():
    return new_doc("Payroll Tax Jurisdiction", jurisdiction_code="NG", jurisdiction_name="Nigeria",
        country_code="NG", currency="NGN", tax_year_start_month=1, tax_year_start_day=1,
        enabled=1).insert(ignore_permissions=True)


def _rule(jurisdiction, *, start, end=None, bands=None):
    return new_doc("Payroll Tax Rule", rule_code="PAYE", rule_name="PAYE Rule",
        jurisdiction=jurisdiction, effective_from=start, effective_to=end,
        calculation_basis="Annualised Period Income",
        bands=bands or [{"band_sequence": 1, "lower_limit": 0, "rate": 10}],
        annual_relief=0, rounding_precision=2, approval_status="Pending", version=1).insert(ignore_permissions=True)


def test_tax_rule_rejects_gapped_bands_and_overlapping_effective_versions(tmp_path):
    setup_finance(tmp_path)
    try:
        jurisdiction = _jurisdiction()
        with pytest.raises(ValidationError, match="contiguous"):
            _rule(jurisdiction.name, start=date(2026, 1, 1), bands=[
                {"band_sequence": 1, "lower_limit": 0, "upper_limit": 1000, "rate": 10},
                {"band_sequence": 2, "lower_limit": 1100, "rate": 20},
            ])
        _rule(jurisdiction.name, start=date(2026, 1, 1), end=date(2026, 6, 30))
        with pytest.raises(ValidationError, match="overlap"):
            _rule(jurisdiction.name, start=date(2026, 6, 1))
    finally:
        teardown()


def test_tax_jurisdiction_rejects_impossible_tax_year_start_date(tmp_path):
    setup_finance(tmp_path)
    try:
        with pytest.raises(ValidationError, match="invalid for the selected month"):
            new_doc("Payroll Tax Jurisdiction", jurisdiction_code="NG", jurisdiction_name="Nigeria",
                country_code="NG", currency="NGN", tax_year_start_month=2,
                tax_year_start_day=31, enabled=1).insert(ignore_permissions=True)
    finally:
        teardown()


def test_employee_tax_profiles_cannot_overlap_for_same_jurisdiction(tmp_path):
    setup_finance(tmp_path)
    try:
        jurisdiction = _jurisdiction()
        rule = _rule(jurisdiction.name, start=date(2026, 1, 1))
        employee = new_doc("Employee", employee_code="TAX-EMP-1", employee_name="Tax Test Employee").insert(ignore_permissions=True)
        new_doc("Employee Tax Profile", employee=employee.name, jurisdiction=jurisdiction.name,
            tax_rule=rule.name, effective_from=date(2026, 1, 1), effective_to=date(2026, 6, 30),
            annual_relief=0, tax_exempt=0, approval_status="Pending").insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="overlap"):
            new_doc("Employee Tax Profile", employee=employee.name, jurisdiction=jurisdiction.name,
                tax_rule=rule.name, effective_from=date(2026, 6, 1), annual_relief=0,
                tax_exempt=0, approval_status="Pending").insert(ignore_permissions=True)
    finally:
        teardown()
