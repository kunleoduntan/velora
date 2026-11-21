"""Statutory relief before PAYE, and protection against components that overwrite payroll values."""
from datetime import date
from decimal import Decimal
import pytest
from velora_erp.finance.payroll_engine import calculate_payroll, PayrollCalculationError

BANDS = [{"lower_limit": 0, "upper_limit": 1000, "rate": 10}, {"lower_limit": 1000, "upper_limit": 3000, "rate": 20}, {"lower_limit": 3000, "upper_limit": None, "rate": 30}]


def _parts(pension_sequence, relief=True):
    return [
        {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000, "taxable": True, "pensionable": True, "sequence": 1},
        {"component_code": "PENSION_EE", "component_type": "Deduction", "calculation_type": "Percentage of Pensionable Gross", "rate": 8, "reduces_taxable_income": relief, "sequence": pension_sequence},
        {"component_code": "PAYE", "component_type": "Deduction", "calculation_type": "Progressive Tax", "periods_per_year": 12, "tax_bands": BANDS, "sequence": 3},
    ]


def test_pension_deduction_reduces_the_pay_that_is_taxed():
    without = calculate_payroll(base_salary=1000, components=_parts(2, relief=False))
    with_relief = calculate_payroll(base_salary=1000, components=_parts(2, relief=True))
    paye = lambda r: next(x["amount"] for x in r["lines"] if x["component_code"] == "PAYE")
    assert paye(with_relief) < paye(without)
    # 1000 less 80 pension = 920 taxable per month, annualised 11,040 against the same bands
    assert Decimal(with_relief["tax_computation"][0]["period_tax"]) == paye(with_relief)


def test_relief_after_the_tax_component_is_refused():
    with pytest.raises(PayrollCalculationError, match="sequenced after the tax"):
        calculate_payroll(base_salary=1000, components=_parts(4))


def test_component_code_cannot_overwrite_a_payroll_value():
    for bad in ("gross", "net", "base_salary", "taxable_gross", "days_worked"):
        with pytest.raises(PayrollCalculationError, match="is reserved"):
            calculate_payroll(base_salary=1000, components=[{"component_code": bad, "component_type": "Earning", "calculation_type": "Fixed", "amount": 10, "sequence": 1}])


def _loan_fixture(tmp_path, rate, loan_date, first_due, principal_repaid):
    from datetime import date
    import velora
    from velora import get_doc, new_doc
    from velora.permissions import Session, session_as
    from velora_erp.setup import after_install
    from velora_erp.finance.engine import get_account_balance
    velora.configure(db_url=f"sqlite:///{tmp_path/'loan.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init()
    try:
        velora.migrate(); after_install()
        today = date.today(); year = today.year
        new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open", is_current=1).insert(ignore_permissions=True)
        new_doc("Financial Period", period_name=f"FY-{year}-OPEN", financial_year=f"FY-{year}", period_number=1, start_date=date(year, 1, 1), end_date=date(year, 12, 31), status="Open").insert(ignore_permissions=True)
        for code, label, root in [("AST", "Assets", "Asset"), ("LIA", "Liabilities", "Liability"), ("INC", "Income", "Income")]:
            new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
        acc = lambda c, n, g, k: new_doc("Account", account_code=c, account_name=n, account_group=g, account_type=k).insert(ignore_permissions=True)
        bank = acc("1000", "Main Bank", "AST", "BANK"); loan_acc = acc("1100", "Employee Loans", "AST", "LOAN_RECEIVABLE")
        payable = acc("2100", "Salary Payable", "LIA", "PAYROLL_PAYABLE"); income = acc("4000", "Loan Interest", "INC", "OTHER_INCOME")
        emp = new_doc("Employee", employee_code="EMP001", employee_name="Test", default_payable_account=payable.name, loan_account=loan_acc.name).insert(ignore_permissions=True)
        maker = Session(user="payroll.preparer", roles=frozenset({"Payroll Officer"})); mgr = Session(user="finance.approver", roles=frozenset({"Finance Manager"}))
        with session_as(maker):
            loan = new_doc("Employee Loan", employee=emp.name, loan_date=loan_date(year), first_repayment_date=first_due(year), principal_amount=1200, annual_interest_rate=rate,
                           term_months=12, repayment_method="Equal Instalment", loan_account=loan_acc.name, interest_income_account=income.name, bank_account=bank.name, currency="NGN", approval_status="Pending").insert(ignore_permissions=True)
        with session_as(mgr):
            loan = get_doc("Employee Loan", loan.name, ignore_permissions=True); loan.approval_status = "Approved"; loan.save(ignore_permissions=True); loan.submit(ignore_permissions=True)
        with session_as(maker):
            rep = new_doc("Employee Loan Repayment", employee_loan=loan.name, employee=emp.name, repayment_date=today, principal_amount=principal_repaid, interest_amount=0,
                          settlement_method="Bank / Cash", bank_account=bank.name, loan_account=loan_acc.name, currency="NGN", approval_status="Pending").insert(ignore_permissions=True)
        with session_as(mgr):
            rep = get_doc("Employee Loan Repayment", rep.name, ignore_permissions=True); rep.approval_status = "Approved"; rep.save(ignore_permissions=True); rep.submit(ignore_permissions=True)
        return get_doc("Employee Loan", loan.name, ignore_permissions=True), emp, loan_acc, get_account_balance
    finally:
        velora.shutdown()


def test_employee_can_settle_a_loan_early(tmp_path):
    loan, emp, loan_acc, bal = _loan_fixture(tmp_path, 0, lambda y: date(y, 1, 2), lambda y: date(y, 2, 1), 1200)
    assert loan.status == "Settled" and loan.outstanding_principal == Decimal("0.00")
    assert all(row.status == "Paid" for row in loan.schedule)


def test_partial_prepayment_lowers_interest_on_the_remaining_instalments(tmp_path):
    from velora_erp.finance.payroll_documents import loan_schedule
    original = loan_schedule(principal=1200, annual_rate=12, months=12, first_date=date(date.today().year, 11, 30))
    old_interest = sum(Decimal(str(r["interest_amount"])) for r in original)
    loan, emp, loan_acc, bal = _loan_fixture(tmp_path, 12, lambda y: date.today(), lambda y: date(y, 11, 30), 600)
    assert loan.outstanding_principal == Decimal("600.00") and loan.status == "Disbursed"
    assert Decimal(str(loan.total_interest)) < old_interest
    # interest on each unpaid instalment is 1% of the principal still outstanding from it onward
    unpaid = [Decimal(str(r.principal_amount)) - Decimal(str(r.paid_principal or 0)) for r in loan.schedule]
    for n, row in enumerate(loan.schedule):
        if unpaid[n] > 0:
            assert Decimal(str(row.interest_amount)) == (sum(unpaid[n:]) * Decimal("0.01")).quantize(Decimal("0.01"))
        else:
            assert row.status == "Paid" and Decimal(str(row.interest_amount)) == 0
    assert sum(unpaid) == Decimal("600.00")


def test_hide_on_payslip_flag_travels_with_the_calculated_line():
    result = calculate_payroll(base_salary=1000, components=[
        {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000, "sequence": 1},
        {"component_code": "PENSION-ER", "component_type": "Employer Contribution", "calculation_type": "Percentage of Base", "rate": 10, "hide_on_payslip": True, "sequence": 2}])
    flags = {x["component_code"]: x["hide_on_payslip"] for x in result["lines"]}
    assert flags == {"BASIC": False, "PENSION-ER": True}
    assert result["net_pay"] == Decimal("1000.00") and result["employer_contributions"] == Decimal("100.00")
