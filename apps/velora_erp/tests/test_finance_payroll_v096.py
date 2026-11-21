from decimal import Decimal
import pytest
from velora_erp.finance.payroll_engine import calculate_payroll, evaluate_formula, payroll_posting_lines, PayrollCalculationError
from velora_erp.finance.payroll_documents import loan_schedule

def test_calculate_payroll_gross_deductions_and_employer_cost():
    result=calculate_payroll(base_salary="1000",components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":"1000","sequence":1,"debit_account":"Salary Expense"},
      {"component_code":"TAX","component_type":"Deduction","calculation_type":"Percentage of Gross","rate":"10","sequence":2,"credit_account":"PAYE Payable"},
      {"component_code":"PENSION_ER","component_type":"Employer Contribution","calculation_type":"Percentage of Base","rate":"5","sequence":3,"debit_account":"Pension Expense","credit_account":"Pension Payable"},
    ])
    assert result["gross_earnings"]==Decimal("1000.00")
    assert result["employee_deductions"]==Decimal("100.00")
    assert result["net_pay"]==Decimal("900.00")
    assert result["employer_contributions"]==Decimal("50.00")
    assert result["total_employer_cost"]==Decimal("1050.00")

def test_calculate_payroll_attendance_proration_and_input():
    result=calculate_payroll(base_salary=3000,days_worked=15,days_in_period=30,components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":3000,"prorate_by_attendance":True},
      {"component_code":"BONUS","component_type":"Earning","calculation_type":"Input"},
    ],inputs={"BONUS":100})
    assert result["gross_earnings"]==Decimal("1600.00")

def test_formula_is_arithmetic_only():
    assert evaluate_formula("base_salary * 0.1 + overtime_hours * 5",{"base_salary":1000,"overtime_hours":2})==Decimal("110.0")
    with pytest.raises(PayrollCalculationError): evaluate_formula("__import__('os').system('id')",{})
    with pytest.raises(PayrollCalculationError): evaluate_formula("base_salary / 0",{"base_salary":1})

def test_payroll_posting_lines_balance_gross_earnings():
    result=calculate_payroll(base_salary=1000,components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":1000,"debit_account":"Salary Expense"},
      {"component_code":"TAX","component_type":"Deduction","calculation_type":"Fixed","amount":100,"credit_account":"PAYE Payable"},
    ])
    lines=payroll_posting_lines(employee="EMP-1",result=result,payroll_payable_account="Salary Payable")
    debit=sum(Decimal(str(x.get("debit",0))) for x in lines); credit=sum(Decimal(str(x.get("credit",0))) for x in lines)
    assert debit==credit==Decimal("1000.00")

def test_loan_schedule_amortises_principal_and_interest():
    rows=loan_schedule(principal=1200,annual_rate=12,months=12,first_date="2027-01-31")
    assert len(rows)==12
    assert rows[0]["interest_amount"]==Decimal("12.00")
    assert rows[-1]["closing_balance"]==Decimal("0.00")
    assert sum((r["principal_amount"] for r in rows),Decimal("0"))==Decimal("1200.00")

def test_equal_principal_schedule():
    rows=loan_schedule(principal=1200,annual_rate=0,months=12,first_date="2027-01-15",method="Equal Principal")
    assert rows[0]["principal_amount"]==Decimal("100.00")
    assert rows[-1]["closing_balance"]==Decimal("0.00")

def test_payroll_rejects_deductions_exceeding_gross():
    with pytest.raises(PayrollCalculationError):
      calculate_payroll(base_salary=100,components=[
       {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":100},
       {"component_code":"DED","component_type":"Deduction","calculation_type":"Fixed","amount":101},
      ])
