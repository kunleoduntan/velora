"""Salary formula/condition workability: static checks at save time, pensionable base, ordering and failure modes."""
from decimal import Decimal
import pytest
from velora_erp.finance.payroll_engine import (PayrollCalculationError, STANDARD_NAMES, calculate_payroll, check_expression, check_expression_names, evaluate_condition)

def comp(code, kind="Earning", calc="Fixed", seq=1, **kw):
    return {"component_code": code, "component_name": code, "component_type": kind, "calculation_type": calc, "sequence": seq, **kw}


def test_check_expression_accepts_real_payroll_formulas_and_reports_names():
    assert check_expression("MAX(base_salary * 0.1, 5000)") == {"base_salary"}
    assert check_expression("IF(gross > 300000 AND grade == 'M3', ROUND(gross * 0.02, 0), 0)".replace("AND", "and")) == {"gross", "grade"}
    assert check_expression("department == 'Sales' AND service_months >= 12", "condition") == {"department", "service_months"}
    assert check_expression("", "condition") == set()


@pytest.mark.parametrize("text", ["base_salary +", "__import__('os')", "base_salary.real", "[1,2]", "lambda: 1", "SUM(gross)", "gross if 1 else 2", "'text'"])
def test_check_expression_rejects_unsafe_or_broken_formulas(text):
    with pytest.raises(PayrollCalculationError):
        check_expression(text, "formula")


def test_unknown_names_are_reported_at_save_time():
    names = check_expression("basic * 0.1 + housng")
    with pytest.raises(PayrollCalculationError, match="housng"):
        check_expression_names(names, set(STANDARD_NAMES) | {"basic"}, "Component PEN")


def test_pensionable_gross_drives_the_nigerian_pension_pattern():
    components = [comp("BASIC", seq=1, amount=200000, pensionable=True, taxable=True), comp("HOUSING", seq=2, amount=100000, pensionable=True, taxable=True),
                  comp("TRANSPORT", seq=3, amount=50000, pensionable=True), comp("BONUS", seq=4, amount=80000, taxable=True),
                  comp("PEN_EE", "Deduction", "Percentage of Pensionable Gross", seq=5, rate=8),
                  comp("PEN_ER", "Employer Contribution", "Percentage of Pensionable Gross", seq=6, rate=10)]
    r = calculate_payroll(base_salary=200000, components=components)
    by = {l["component_code"]: l["amount"] for l in r["lines"]}
    assert by["PEN_EE"] == Decimal("28000.00") and by["PEN_ER"] == Decimal("35000.00")      # 350,000 pensionable, bonus excluded
    assert r["gross_earnings"] == Decimal("430000.00")


def test_a_formula_can_only_use_earlier_components():
    ok = [comp("BASIC", amount=1000, seq=1), comp("ALLOW", calc="Formula", formula="BASIC * 0.5", seq=2)]
    assert calculate_payroll(base_salary=1000, components=ok)["gross_earnings"] == Decimal("1500.00")
    late = [comp("ALLOW", calc="Formula", formula="BASIC * 0.5", seq=1), comp("BASIC", amount=1000, seq=2)]
    with pytest.raises(PayrollCalculationError, match="unknown payroll value"):
        calculate_payroll(base_salary=1000, components=late)


def test_conditions_skip_a_component_and_set_its_code_to_zero():
    components = [comp("BASIC", amount=1000, seq=1), comp("LONG", amount=300, seq=2, condition="service_months >= 24"),
                  comp("TOP", calc="Formula", formula="LONG + 1", seq=3)]
    r = calculate_payroll(base_salary=1000, components=components, employee_context={"service_months": 6})
    assert {l["component_code"] for l in r["lines"]} == {"BASIC", "TOP"} and r["gross_earnings"] == Decimal("1001.00")
    r = calculate_payroll(base_salary=1000, components=components, employee_context={"service_months": 30})
    assert r["gross_earnings"] == Decimal("1601.00")


def test_condition_comparing_text_with_a_number_is_a_payroll_error_not_a_crash():
    with pytest.raises(PayrollCalculationError):
        evaluate_condition("department > 5", {"department": "Sales"})


def test_negative_results_and_division_by_zero_are_refused_clearly():
    with pytest.raises(PayrollCalculationError, match="negative"):
        calculate_payroll(base_salary=100, components=[comp("X", calc="Formula", formula="base_salary - 500")])
    with pytest.raises(PayrollCalculationError, match="division by zero"):
        calculate_payroll(base_salary=100, components=[comp("X", calc="Formula", formula="base_salary / days_in_period")])
