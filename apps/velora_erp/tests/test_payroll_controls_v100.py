from decimal import Decimal
import pytest

from velora_erp.finance.payroll_engine import (
    PayrollCalculationError, calculate_payroll, build_statutory_contribution_register,
    reconcile_payroll_settlements,
)


def test_employer_contribution_posts_expense_and_liability_using_dedicated_pair():
    result = calculate_payroll(base_salary=1000, components=[
        {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000,
         "debit_account": "SALARY-EXP"},
        {"component_code": "PENSION-ER", "component_type": "Employer Contribution", "calculation_type": "Percentage of Base", "rate": 5,
         "debit_account": "PENSION-EXP", "credit_account": "PENSION-PAY", "statutory_scheme": "PENSION"},
    ])
    contribution = result["lines"][1]
    assert contribution["amount"] == Decimal("50.00")
    assert contribution["debit_account"] == "PENSION-EXP"
    assert contribution["credit_account"] == "PENSION-PAY"
    assert contribution["statutory_scheme"] == "PENSION"


def test_statutory_contribution_register_uses_submitted_slip_snapshots_only():
    register = build_statutory_contribution_register(
        salary_slips=[{"name": "SS-1", "docstatus": 1, "period_start": "2026-11-01", "period_end": "2026-11-30",
            "currency": "NGN", "calculation_lines": [
                {"component_code": "PENSION-ER", "component_type": "Employer Contribution", "amount": "50", "statutory_scheme": "PENSION", "credit_account": "PENSION-PAY"},
                {"component_code": "PENSION-EE", "component_type": "Deduction", "amount": "40", "statutory_scheme": "PENSION", "credit_account": "PENSION-PAY"},
            ]}], period_start="2026-11-01", period_end="2026-11-30", currency="NGN")
    assert register["complete"] is True
    assert register["total_amount"] == Decimal("90.00")
    assert len(register["rows"]) == 2
    with pytest.raises(PayrollCalculationError, match="submitted"):
        build_statutory_contribution_register(salary_slips=[{"name": "DRAFT", "docstatus": 0}],
            period_start="2026-11-01", period_end="2026-11-30", currency="NGN")


def test_payroll_payment_reconciliation_detects_missing_or_duplicate_posted_settlements():
    slips=[{"salary_slip":"SS-1", "net_pay":1000, "paid_amount":600, "outstanding_amount":400}]
    lines=[{"payment":"PP-1", "salary_slip":"SS-1", "amount":300},
           {"payment":"PP-2", "salary_slip":"SS-1", "amount":300}]
    result=reconcile_payroll_settlements(salary_slips=slips, posted_payment_lines=lines)
    assert result["reconciled"] is True
    assert result["results"][0]["payment_implied_outstanding"] == Decimal("400.00")
    result=reconcile_payroll_settlements(salary_slips=slips, posted_payment_lines=lines[:1])
    assert result["reconciled"] is False
    with pytest.raises(PayrollCalculationError, match="Duplicate Salary Slip line"):
        reconcile_payroll_settlements(salary_slips=slips, posted_payment_lines=[lines[0], lines[0]])


def test_payroll_payment_reconciliation_rejects_inconsistent_salary_slip_balances():
    with pytest.raises(PayrollCalculationError, match="do not reconcile"):
        reconcile_payroll_settlements(salary_slips=[{"salary_slip":"SS-1", "net_pay":1000,
            "paid_amount":600, "outstanding_amount":450}], posted_payment_lines=[])


def test_salary_component_employer_mapping_requires_expense_and_liability_accounts(monkeypatch):
    from types import SimpleNamespace
    import velora_erp.finance.payroll_documents as payroll_docs

    def account(name, roots=None, party=False):
        if name == "PENSION-EXP" and roots == ["Expense"]:
            return {"name": name}
        if name == "PENSION-PAY" and roots == ["Liability"]:
            return {"name": name}
        raise ValueError(f"Invalid account mapping: {name} {roots}")

    monkeypatch.setattr(payroll_docs, "_account", account)
    component = SimpleNamespace(component_code="PENSION_ER", component_name="Employer Pension",
        component_type="Employer Contribution", calculation_type="Fixed", amount=0, rate=0,
        account=None, debit_account="PENSION-EXP", credit_account="PENSION-PAY",
        employer_expense_account=None, employer_payable_account=None)
    payroll_docs.SalaryComponent.validate(component)
    assert component.employer_expense_account == "PENSION-EXP"
    assert component.employer_payable_account == "PENSION-PAY"

    component.employer_payable_account = "PENSION-EXP"
    with pytest.raises(ValueError, match="Invalid account mapping"):
        payroll_docs.SalaryComponent.validate(component)
