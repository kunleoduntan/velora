from datetime import date
from decimal import Decimal

import pytest
import velora
from velora import get_doc, new_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.setup import after_install
from velora_erp.finance.engine import get_account_balance, post_financial_transaction
from velora_erp.finance.payroll_engine import calculate_payroll, PayrollCalculationError

MAKER = Session("yearend.preparer@example.test", frozenset({"Accountant", "Payroll Officer"}))
MANAGER = Session("yearend.approver@example.test", frozenset({"Finance Manager"}))

BANDS = [
    {"lower_limit": 0, "upper_limit": 1000, "rate": 10},
    {"lower_limit": 1000, "upper_limit": None, "rate": 20},
]


def test_cumulative_ytd_payroll_tax_uses_prior_taxable_income_and_withholding():
    result = calculate_payroll(base_salary=1000, components=[
        {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000, "taxable": True, "sequence": 1},
        {"component_code": "PAYE", "component_type": "Deduction", "calculation_type": "Progressive Tax", "tax_bands": BANDS,
         "tax_calculation_basis": "Cumulative YTD", "periods_per_year": 12, "prior_periods_elapsed": 1,
         "prior_ytd_taxable_income": 1000, "prior_tax_withheld": 100, "tax_rule": "RULE-1", "tax_year_start": "2026-01-01",
         "tax_liability_account": "PAYE-PAYABLE", "annual_relief": 0, "rounding_precision": 2, "sequence": 2},
    ])
    tax = result["tax_computation"][0]
    assert tax["periods_elapsed"] == "2"
    assert Decimal(tax["projected_annual_taxable_income"]) == Decimal("12000.00")
    assert Decimal(tax["current_period_adjustment"]) == Decimal("283.33")
    assert Decimal(tax["actual_withheld"]) == Decimal("283.33")
    assert result["employee_deductions"] == Decimal("283.33")


def test_cumulative_ytd_overwithholding_creates_credit_review_signal_not_negative_deduction():
    result = calculate_payroll(base_salary=1000, components=[
        {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000, "taxable": True, "sequence": 1},
        {"component_code": "PAYE", "component_type": "Deduction", "calculation_type": "Progressive Tax", "tax_bands": BANDS,
         "tax_calculation_basis": "Cumulative YTD", "periods_per_year": 12, "prior_periods_elapsed": 1,
         "prior_ytd_taxable_income": 1000, "prior_tax_withheld": 500, "tax_rule": "RULE-1", "tax_year_start": "2026-01-01",
         "tax_liability_account": "PAYE-PAYABLE", "annual_relief": 0, "rounding_precision": 2, "sequence": 2},
    ])
    tax = result["tax_computation"][0]
    assert Decimal(tax["current_period_adjustment"]) < 0
    assert Decimal(tax["refund_credit_amount"]) > 0
    assert tax["requires_refund_or_credit_review"] is True
    assert result["employee_deductions"] == Decimal("0.00")
    assert result["net_pay"] == Decimal("1000.00")


def test_cumulative_ytd_rejects_more_periods_than_tax_year():
    with pytest.raises(PayrollCalculationError, match="more processed periods"):
        calculate_payroll(base_salary=1000, components=[
            {"component_code": "BASIC", "component_type": "Earning", "calculation_type": "Fixed", "amount": 1000, "taxable": True},
            {"component_code": "PAYE", "component_type": "Deduction", "calculation_type": "Progressive Tax", "tax_bands": BANDS,
             "tax_calculation_basis": "Cumulative YTD", "periods_per_year": 12, "prior_periods_elapsed": 12,
             "prior_ytd_taxable_income": 12000, "prior_tax_withheld": 1000},
        ])


def _account(code, name, group, kind):
    return new_doc("Account", account_code=code, account_name=name, account_group=group, account_type=kind).insert(ignore_permissions=True)


def _close_prior_period(name, period_end):
    from velora_erp.finance.doctype.financial_period_close.financial_period_close import CHECKLIST as PERIOD_CHECKLIST
    checklist = [{"item_code": code, "description": description, "completed": 1,
                  "evidence_reference": f"TEST-EVIDENCE-{code}-{name}", "reviewer_notes": "Reviewed in year-end workflow integration test."}
                 for code, description in PERIOD_CHECKLIST]
    with session_as(MAKER):
        close = new_doc("Financial Period Close", financial_period=name, close_date=period_end,
                        checklist=checklist, approval_status="Pending").insert(ignore_permissions=True)
    with session_as(MANAGER):
        close = get_doc("Financial Period Close", close.name, ignore_permissions=True)
        close.approval_status = "Approved"
        close.save(ignore_permissions=True)
        close.submit(ignore_permissions=True)
    return close


def test_year_end_close_creates_approved_balanced_journal_and_closes_final_period_and_year(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'year-end-close.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init()
    try:
        velora.migrate(); after_install()
        from velora.application_workspaces import listing
        workspaces = listing()
        period_end = next(x for x in workspaces if x.get("scope")=="company" and x.get("name")=="Period End")
        payroll_workspace = next(x for x in workspaces if x.get("scope")=="company" and x.get("name")=="Payroll & Employee Finance")
        assert any(w.get("route")=="#/app/Year End Close" for w in period_end.get("layout",[]))
        assert any(w.get("route")=="#/app/Tax Refund Credit Review" for w in payroll_workspace.get("layout",[]))
        settings = get_doc("Finance Settings", "Primary Finance Settings", ignore_permissions=True)
        settings.base_currency = "NGN"
        settings.save(ignore_permissions=True)
        fy = new_doc("Financial Year", year_name="FY-2025", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
                     status="Open", is_current=1).insert(ignore_permissions=True)
        periods = []
        for month in range(1, 13):
            start = date(2025, month, 1)
            if month == 12:
                end = date(2025, 12, 31)
            else:
                from calendar import monthrange
                end = date(2025, month, monthrange(2025, month)[1])
            period = new_doc("Financial Period", period_name=f"FY-2025-P{month:02d}", financial_year=fy.name,
                period_number=month, start_date=start, end_date=end, status="Open").insert(ignore_permissions=True)
            periods.append(period)
        for code, label, root in [("AST", "Assets", "Asset"), ("EQT", "Equity", "Equity"),
                                  ("INC", "Income", "Income"), ("EXP", "Expenses", "Expense")]:
            new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
        bank = _account("1000", "Main Bank", "AST", "BANK")
        retained = _account("3000", "Retained Earnings", "EQT", "EQUITY")
        revenue = _account("4000", "Sales Revenue", "INC", "REVENUE")
        expense = _account("5000", "Operating Expense", "EXP", "OPERATING_EXPENSE")
        for period in periods[:-1]:
            _close_prior_period(period.name, period.end_date)
        post_financial_transaction(source_doctype="Test Source", source_name="FY25-RESULT", posting_date=date(2025, 12, 31),
            currency="NGN", lines=[
                {"account": bank.name, "debit": 1000, "credit": 0},
                {"account": revenue.name, "debit": 0, "credit": 1000},
                {"account": expense.name, "debit": 600, "credit": 0},
                {"account": bank.name, "debit": 0, "credit": 600},
            ])
        from wf_helpers import install_approval, decide
        install_approval("Year End Close")
        with session_as(MAKER):
            close = new_doc("Year End Close", financial_year=fy.name, posting_date=date(2025, 12, 31),
                retained_earnings_account=retained.name, approval_status="Pending").insert(ignore_permissions=True)
            for item in close.checklist:
                item.completed = 1
                item.evidence_reference = f"YE25-{item.item_code}"
                item.reviewer_notes = "Reviewed and reconciled for FY2025."
            close.save(ignore_permissions=True)
        assert close.net_profit == Decimal("400.00")
        assert close.total_debit == close.total_credit
        decide("Year End Close", close.name, "Approve", MANAGER)
        # A balanced balance-sheet posting after approval must invalidate the approved source fingerprint.
        post_financial_transaction(source_doctype="Test Source", source_name="FY25-BS-ADJUSTMENT", posting_date=date(2025, 12, 31),
            currency="NGN", lines=[{"account": bank.name, "debit": 50, "credit": 0},
                                   {"account": retained.name, "debit": 0, "credit": 50}])
        with session_as(MANAGER):
            close = get_doc("Year End Close", close.name, ignore_permissions=True)
            with pytest.raises(ValidationError, match="approved Year End Close is immutable"):
                close.submit(ignore_permissions=True)
        decide("Year End Close", close.name, "Reopen", MANAGER, "balances moved after approval")
        with session_as(MANAGER):
            close = get_doc("Year End Close", close.name, ignore_permissions=True)
            close.save(ignore_permissions=True)                                   # refreshes the source balances while Pending
        decide("Year End Close", close.name, "Approve", MANAGER)
        with session_as(MANAGER):
            close = get_doc("Year End Close", close.name, ignore_permissions=True)
            close.submit(ignore_permissions=True)
        posted = get_doc("Year End Close", close.name, ignore_permissions=True)
        assert posted.docstatus == 1
        assert posted.status == "Closed"
        assert posted.posting_batch
        assert get_doc("Financial Year", fy.name, ignore_permissions=True).status == "Closed"
        assert get_doc("Financial Period", periods[-1].name, ignore_permissions=True).status == "Closed"
        assert get_account_balance(revenue.name, as_of=date(2025, 12, 31)) == Decimal("0.000000")
        assert get_account_balance(expense.name, as_of=date(2025, 12, 31)) == Decimal("0.000000")
        assert get_account_balance(retained.name, as_of=date(2025, 12, 31)) == Decimal("-450.000000")
    finally:
        velora.shutdown()


def test_payroll_run_integrates_cumulative_paye_and_requires_approved_tax_credit_before_posting(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'cumulative-paye.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init()
    try:
        velora.migrate(); after_install()
        from velora.application_workspaces import listing
        payroll_workspace = next(x for x in listing() if x.get("scope")=="company" and x.get("name")=="Payroll & Employee Finance")
        assert any(w.get("route")=="#/app/Tax Refund Credit Review" for w in payroll_workspace.get("layout",[]))
        settings = get_doc("Finance Settings", "Primary Finance Settings", ignore_permissions=True)
        settings.base_currency = "NGN"
        settings.save(ignore_permissions=True)
        year = 2026
        new_doc("Financial Year", year_name="FY-2026", start_date=date(year, 1, 1), end_date=date(year, 12, 31),
                status="Open", is_current=1).insert(ignore_permissions=True)
        from calendar import monthrange
        for month in range(1, 13):
            new_doc("Financial Period", period_name=f"FY-2026-P{month:02d}", financial_year="FY-2026",
                period_number=month, start_date=date(year, month, 1),
                end_date=date(year, month, monthrange(year, month)[1]), status="Open").insert(ignore_permissions=True)
        for code, label, root in [("AST", "Assets", "Asset"), ("LIA", "Liabilities", "Liability"),
                                  ("EXP", "Expenses", "Expense"), ("INC", "Income", "Income")]:
            new_doc("Account Group", group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
        bank = _account("1000", "Payroll Bank", "AST", "BANK")
        payable = _account("2100", "Salary Payable", "LIA", "PAYROLL_PAYABLE")
        tax_payable = _account("2110", "PAYE Payable", "LIA", "TAX_PAYABLE")
        salary_expense = _account("5000", "Salary Expense", "EXP", "OPERATING_EXPENSE")
        employee = new_doc("Employee", employee_code="YTD-EMP", employee_name="YTD Test Employee",
                           default_payable_account=payable.name).insert(ignore_permissions=True)
        with session_as(MAKER):
            jurisdiction = new_doc("Payroll Tax Jurisdiction", jurisdiction_code="NG", jurisdiction_name="Nigeria",
                country_code="NG", currency="NGN", tax_year_start_month=1, tax_year_start_day=1, enabled=1).insert(ignore_permissions=True)
            high_rule = new_doc("Payroll Tax Rule", rule_code="PAYE-HIGH", rule_name="Prior PAYE Rate",
                jurisdiction=jurisdiction.name, effective_from=date(year, 1, 1), effective_to=date(year, 11, 30),
                calculation_basis="Annualised Period Income", bands=[{"band_sequence": 1, "lower_limit": 0, "rate": 50}],
                annual_relief=0, rounding_precision=2, approval_status="Pending", version=1).insert(ignore_permissions=True)
            low_rule = new_doc("Payroll Tax Rule", rule_code="PAYE-LOW", rule_name="Cumulative PAYE Rate",
                jurisdiction=jurisdiction.name, effective_from=date(year, 12, 1),
                calculation_basis="Cumulative YTD", bands=[{"band_sequence": 1, "lower_limit": 0, "rate": 1}],
                annual_relief=0, rounding_precision=2, approval_status="Pending", version=1).insert(ignore_permissions=True)
        with session_as(MANAGER):
            for rule_name in (high_rule.name, low_rule.name):
                rule = get_doc("Payroll Tax Rule", rule_name, ignore_permissions=True)
                rule.approval_status = "Approved"; rule.save(ignore_permissions=True); rule.submit(ignore_permissions=True)
        with session_as(MAKER):
            profile = new_doc("Employee Tax Profile", employee=employee.name, jurisdiction=jurisdiction.name,
                tax_rule=high_rule.name, effective_from=date(year, 1, 1), effective_to=date(year, 11, 30),
                annual_relief=0, tax_exempt=0, approval_status="Pending").insert(ignore_permissions=True)
            basic = new_doc("Salary Component", component_code="BASIC", component_name="Basic Salary",
                component_type="Earning", calculation_type="Fixed", amount=1000, sequence=1, taxable=1,
                account=salary_expense.name).insert(ignore_permissions=True)
            paye = new_doc("Salary Component", component_code="PAYE", component_name="PAYE",
                component_type="Deduction", calculation_type="Progressive Tax", tax_rule=high_rule.name,
                periods_per_year=12, sequence=2, account=tax_payable.name).insert(ignore_permissions=True)
            structure = new_doc("Salary Structure", structure_name="YTD Monthly", pay_frequency="Monthly", currency="NGN",
                components=[{"salary_component": basic.name}, {"salary_component": paye.name}], approval_status="Pending").insert(ignore_permissions=True)
        with session_as(MANAGER):
            profile = get_doc("Employee Tax Profile", profile.name, ignore_permissions=True)
            profile.approval_status = "Approved"; profile.save(ignore_permissions=True); profile.submit(ignore_permissions=True)
            structure = get_doc("Salary Structure", structure.name, ignore_permissions=True)
            structure.approval_status = "Approved"; structure.save(ignore_permissions=True); structure.submit(ignore_permissions=True)
        with session_as(MAKER):
            assignment = new_doc("Salary Structure Assignment", employee=employee.name, salary_structure=structure.name,
                effective_from=date(year, 1, 1), base_salary=1000, currency="NGN", status="Draft", approval_status="Pending").insert(ignore_permissions=True)
        with session_as(MANAGER):
            assignment = get_doc("Salary Structure Assignment", assignment.name, ignore_permissions=True)
            assignment.approval_status = "Approved"; assignment.save(ignore_permissions=True); assignment.submit(ignore_permissions=True)
        with session_as(MAKER):
            first = new_doc("Payroll Run", run_title="November Payroll", pay_frequency="Monthly",
                period_start=date(year, 11, 1), period_end=date(year, 11, 30), posting_date=date(year, 11, 30),
                currency="NGN", payroll_payable_account=payable.name,
                employees=[{"employee": employee.name, "salary_assignment": assignment.name}], approval_status="Pending").insert(ignore_permissions=True)
        with session_as(MANAGER):
            first = get_doc("Payroll Run", first.name, ignore_permissions=True)
            first.approval_status = "Approved"; first.save(ignore_permissions=True); first.submit(ignore_permissions=True)
        first_slip = get_doc("Salary Slip", first.employees[0].salary_slip, ignore_permissions=True)
        first_tax = next(x for x in first_slip.lines if x.component_code == "PAYE")
        assert first_tax.amount == Decimal("500.00")
        with session_as(MAKER):
            next_profile = new_doc("Employee Tax Profile", employee=employee.name, jurisdiction=jurisdiction.name,
                tax_rule=low_rule.name, effective_from=date(year, 12, 1), annual_relief=0, tax_exempt=0,
                approval_status="Pending").insert(ignore_permissions=True)
        with session_as(MANAGER):
            next_profile = get_doc("Employee Tax Profile", next_profile.name, ignore_permissions=True)
            next_profile.approval_status = "Approved"; next_profile.save(ignore_permissions=True); next_profile.submit(ignore_permissions=True)
        from wf_helpers import install_approval, decide
        install_approval("Tax Refund Credit Review")
        with session_as(MAKER):
            second = new_doc("Payroll Run", run_title="December Payroll", pay_frequency="Monthly",
                period_start=date(year, 12, 1), period_end=date(year, 12, 31), posting_date=date(year, 12, 31),
                currency="NGN", payroll_payable_account=payable.name,
                employees=[{"employee": employee.name, "salary_assignment": assignment.name}], approval_status="Pending").insert(ignore_permissions=True)
        review_rows = __import__("velora").get_list("Tax Refund Credit Review", filters=[["payroll_run", "=", second.name]],
            fields=["name", "proposed_credit_amount", "status"], limit=10, ignore_permissions=True)
        assert len(review_rows) == 1
        assert Decimal(str(review_rows[0]["proposed_credit_amount"])) == Decimal("480.00")
        assert review_rows[0]["status"] == "Pending Review"
        with session_as(MANAGER):
            second = get_doc("Payroll Run", second.name, ignore_permissions=True)
            second.approval_status = "Approved"; second.save(ignore_permissions=True)
            with pytest.raises(ValidationError, match="PAYE refund/credit"):
                second.submit(ignore_permissions=True)
            second.approval_status = "Pending"; second.save(ignore_permissions=True)
        decide("Tax Refund Credit Review", review_rows[0]["name"], "Approve", MANAGER)
        # A subsequently posted backdated payroll changes the YTD source. The previous credit approval must be invalidated.
        with session_as(MAKER):
            september = new_doc("Payroll Run", run_title="September Payroll", pay_frequency="Monthly",
                period_start=date(year, 9, 1), period_end=date(year, 9, 30), posting_date=date(year, 9, 30),
                currency="NGN", payroll_payable_account=payable.name,
                employees=[{"employee": employee.name, "salary_assignment": assignment.name}], approval_status="Pending").insert(ignore_permissions=True)
        with session_as(MANAGER):
            september = get_doc("Payroll Run", september.name, ignore_permissions=True)
            september.approval_status = "Approved"; september.save(ignore_permissions=True); september.submit(ignore_permissions=True)
        with session_as(MAKER):
            second = get_doc("Payroll Run", second.name, ignore_permissions=True)
            second.save(ignore_permissions=True)
        review = get_doc("Tax Refund Credit Review", review_rows[0]["name"], ignore_permissions=True)
        assert review.status == "Pending Review"
        assert review.approval_status == "Pending"
        assert review.proposed_credit_amount == Decimal("970.00")
        decide("Tax Refund Credit Review", review.name, "Approve", MANAGER)          # the instance followed the system reset, so it can be approved again
        with session_as(MAKER):
            second = get_doc("Payroll Run", second.name, ignore_permissions=True)
            second.save(ignore_permissions=True)
        assert second.employees[0].tax_credit_amount == Decimal("970.00")
        assert second.employees[0].net_pay == Decimal("1970.00")
        with session_as(MANAGER):
            second = get_doc("Payroll Run", second.name, ignore_permissions=True)
            second.approval_status = "Approved"; second.save(ignore_permissions=True); second.submit(ignore_permissions=True)
        applied = get_doc("Tax Refund Credit Review", review_rows[0]["name"], ignore_permissions=True)
        assert applied.status == "Applied"
        assert applied.posting_batch == second.posting_batch
        assert get_account_balance(tax_payable.name, as_of=date(year, 12, 31)) == Decimal("-30.000000")
        second_slip = get_doc("Salary Slip", second.employees[0].salary_slip, ignore_permissions=True)
        assert second_slip.net_pay == Decimal("1970.00")
        assert second_slip.tax_credit_amount == Decimal("970.00")
        from velora_erp.finance.report.payroll_register.payroll_register import execute as payroll_register
        register = payroll_register({"employee": employee.name, "from_date": "2026-12-01", "to_date": "2026-12-31"})
        assert any(row.values.get("tax_credit_amount") == Decimal("970.00") for row in register.rows)
    finally:
        velora.shutdown()
