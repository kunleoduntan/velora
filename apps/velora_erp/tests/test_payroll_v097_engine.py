from decimal import Decimal
import pytest
from velora_erp.finance.payroll_engine import calculate_payroll,evaluate_formula,evaluate_condition,PayrollCalculationError
from velora_erp.finance.tax_engine import progressive_tax,calculate_period_tax
from velora_erp.finance.control_reconciliation import reconcile_control,ControlReconciliationError

def test_salary_slip_field_mapping_formula_and_earnings_deduction():
    r=calculate_payroll(base_salary=1000,inputs={"bonus":150,"surcharge":25},components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":1000,"sequence":1},
      {"component_code":"BONUS","component_type":"Earning","calculation_type":"Formula","formula":"bonus * 1","input_fieldname":"bonus","sequence":2},
      {"component_code":"SURCHARGE","component_type":"Deduction","calculation_type":"Formula","formula":"surcharge * 1","input_fieldname":"surcharge","sequence":3},
    ])
    assert [x["component_type"] for x in r["lines"]]==["Earning","Earning","Deduction"]
    assert r["lines"][1]["amount"]==Decimal("150.00")
    assert r["lines"][2]["amount"]==Decimal("25.00")
    assert r["net_pay"]==Decimal("1125.00")

def test_expression_language_functions_and_conditions():
    assert evaluate_formula("MIN(MAX(base_salary * 0.2, 100), 500) + ROUND(ABS(-2.345), 2)",{"base_salary":1000})==Decimal("202.35")
    assert evaluate_formula("IF(base_salary > 1000, base_salary * 0.1, 25)",{"base_salary":2000})==Decimal("200.0")
    assert evaluate_condition("employment_type == 'Permanent' AND base_salary >= 1000",{"employment_type":"Permanent","base_salary":1000})
    assert not evaluate_condition("employment_type == 'Contract' OR base_salary < 500",{"employment_type":"Permanent","base_salary":1000})
    result=calculate_payroll(base_salary=1000,employee_context={"employee_type":"Permanent"},components=[{"component_code":"ALLOW","component_type":"Earning","calculation_type":"Fixed","amount":100,"condition":"employee_type == 'Permanent'"}])
    assert result["gross_earnings"]==Decimal("100.00")
    with pytest.raises(PayrollCalculationError): evaluate_formula("__import__('os')",{})

def test_progressive_tax_bands():
    bands=[{"lower_limit":0,"upper_limit":1000,"rate":10},{"lower_limit":1000,"upper_limit":3000,"rate":20},{"lower_limit":3000,"upper_limit":None,"rate":30}]
    assert progressive_tax(4000,bands)==Decimal("800.00")
    result=calculate_period_tax(period_taxable_income=1000,periods_per_year=12,bands=bands)
    assert result["annual_tax"]==Decimal("3200.00")
    assert result["period_tax"]==Decimal("266.67")
    period_basis=calculate_period_tax(period_taxable_income=1000,periods_per_year=12,bands=bands,calculation_basis="Period Taxable Income")
    assert period_basis["period_tax"]==Decimal("100.00")

def test_control_reconciliation_never_posts_automatic_journal():
    r=reconcile_control(control_type="Employee Loans",control_account="LOAN-REC",gl_balance="800",source_balances=[{"source_type":"Employee Loan","source_name":"LN-1","balance":"750"}])
    assert r["status"]=="Exception" and r["difference"]==Decimal("-50") and not r["automatic_journal"]
    with pytest.raises(ControlReconciliationError): reconcile_control(control_type="Magic",control_account="x",gl_balance=0,source_balances=[])

def test_loan_interest_recovery_is_separate_from_principal_recovery():
    from velora_erp.finance.payroll_engine import payroll_posting_lines
    result=calculate_payroll(base_salary=1000,components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":1000,"debit_account":"Salary Expense","sequence":1},
      {"component_code":"LOAN_PRINCIPAL","component_type":"Loan Repayment","calculation_type":"Input","credit_account":"Loan Receivable","sequence":2},
      {"component_code":"LOAN_INTEREST","component_type":"Loan Interest Recovery","calculation_type":"Input","credit_account":"Loan Interest Income","sequence":3},
    ],inputs={"LOAN_PRINCIPAL":50,"LOAN_INTEREST":10})
    assert result["loan_repayments"]==Decimal("50.00")
    assert result["loan_interest_repayments"]==Decimal("10.00")
    assert result["net_pay"]==Decimal("940.00")
    lines=payroll_posting_lines(employee="EMP-1",result=result,payroll_payable_account="Salary Payable")
    interest=next(x for x in lines if x["account"]=="Loan Interest Income")
    assert interest["credit"]==Decimal("10.00") and interest.get("party") is None

def test_progressive_tax_salary_component_uses_effective_rule_bands():
    result=calculate_payroll(base_salary=1000,components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":1000,"taxable":True,"sequence":1},
      {"component_code":"PAYE","component_type":"Deduction","calculation_type":"Progressive Tax","tax_rule":"NG-PAYE-2026","periods_per_year":12,"tax_bands":[{"lower_limit":0,"upper_limit":1000,"rate":10},{"lower_limit":1000,"upper_limit":3000,"rate":20},{"lower_limit":3000,"upper_limit":None,"rate":30}],"sequence":2},
    ])
    assert result["employee_deductions"]==Decimal("266.67")
    assert result["tax_computation"][0]["tax_rule"]=="NG-PAYE-2026"

def test_schedule_driven_loan_component_uses_due_amount_snapshot():
    result=calculate_payroll(base_salary=1000,components=[
      {"component_code":"BASIC","component_type":"Earning","calculation_type":"Fixed","amount":1000,"sequence":1},
      {"component_code":"LOAN_PRINCIPAL","component_type":"Loan Repayment","calculation_type":"Scheduled Loan Deduction","scheduled_amount":75,"credit_account":"LOAN-REC","sequence":2},
      {"component_code":"LOAN_INTEREST","component_type":"Loan Interest Recovery","calculation_type":"Scheduled Loan Interest","scheduled_amount":5,"credit_account":"LOAN-INT","sequence":3},
    ])
    assert result["loan_repayments"]==Decimal("75.00")
    assert result["loan_interest_repayments"]==Decimal("5.00")
    assert result["net_pay"]==Decimal("920.00")
