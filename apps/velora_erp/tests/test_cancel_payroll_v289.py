"""Cancel for payroll, loans and advances: the slips go with the run, every balance goes back."""
from datetime import date, timedelta
from decimal import Decimal
import velora
from velora import get_doc, new_doc
from velora.permissions import Session, session_as
from velora_erp.setup import after_install
from velora_erp.finance.engine import get_account_balance


def _account(code, name, group, kind):
    return new_doc("Account", account_code=code, account_name=name, account_group=group, account_type=kind).insert(ignore_permissions=True)


def test_payroll_chain_cancels_newest_first_and_every_balance_goes_back(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'payroll.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init()
    try:
        velora.migrate(); after_install()
        from velora.application_workspaces import listing
        assert any(x.get("name")=="Payroll & Employee Finance" for x in listing())
        hr_workspace = next(x for x in listing() if x.get("name") == "HR & People")
        assert hr_workspace["visibility"] == "roles"
        assert set(hr_workspace["roles"]) == {"HR Manager", "HR Officer"}
        today=date.today(); year=today.year
        new_doc("Financial Year",year_name=f"FY-{year}",start_date=date(year,1,1),end_date=date(year,12,31),status="Open",is_current=1).insert(ignore_permissions=True)
        new_doc("Financial Period",period_name=f"FY-{year}-OPEN",financial_year=f"FY-{year}",period_number=1,start_date=date(year,1,1),end_date=date(year,12,31),status="Open").insert(ignore_permissions=True)
        for code,label,root in [("AST","Assets","Asset"),("LIA","Liabilities","Liability"),("EXP","Expenses","Expense"),("INC","Income","Income")]:
            new_doc("Account Group",group_code=code,group_name=label,root_type=root,is_group=0).insert(ignore_permissions=True)
        bank=_account("1000","Main Bank","AST","BANK")
        loan=_account("1100","Employee Loan Receivable","AST","LOAN_RECEIVABLE")
        advance=_account("1101","Employee Advance Receivable","AST","LOAN_RECEIVABLE")
        salary_payable=_account("2100","Salary Payable","LIA","PAYROLL_PAYABLE")
        tax_payable=_account("2110","PAYE Payable","LIA","TAX_PAYABLE")
        salary_expense=_account("5000","Salary Expense","EXP","OPERATING_EXPENSE")
        interest_income=_account("4000","Employee Loan Interest Income","INC","OTHER_INCOME")
        employee=new_doc("Employee",employee_code="EMP001",employee_name="Test Employee",default_payable_account=salary_payable.name,loan_account=loan.name,advance_account=advance.name).insert(ignore_permissions=True)
        maker=Session(user="payroll.preparer",roles=frozenset({"Payroll Officer"}))
        manager=Session(user="finance.approver",roles=frozenset({"Finance Manager"}))
        manager2=Session(user="finance.approver2",roles=frozenset({"Finance Manager"}))
        with session_as(Session(user="Administrator",roles=frozenset({"System Manager"}))):
            from velora.meta.extensions import add_custom_field
            add_custom_field("Salary Slip",{"fieldname":"bonus","fieldtype":"Currency","label":"Performance Bonus"})
        with session_as(maker):
            employee_loan=new_doc("Employee Loan",employee=employee.name,loan_date=date(year,11,1),first_repayment_date=date(year,11,17),principal_amount=1200,annual_interest_rate=12,term_months=12,repayment_method="Equal Instalment",loan_account=loan.name,interest_income_account=interest_income.name,bank_account=bank.name,currency="NGN",approval_status="Pending").insert(ignore_permissions=True)
            employee_advance=new_doc("Employee Advance",employee=employee.name,advance_date=today,purpose="Business travel",amount=300,currency="NGN",advance_account=advance.name,bank_account=bank.name,recovery_method="Payroll Deduction",approval_status="Pending").insert(ignore_permissions=True)
        with session_as(manager):
            employee_loan=get_doc("Employee Loan",employee_loan.name,ignore_permissions=True); employee_loan.approval_status="Approved"; employee_loan.save(ignore_permissions=True); employee_loan.submit(ignore_permissions=True)
            employee_advance=get_doc("Employee Advance",employee_advance.name,ignore_permissions=True); employee_advance.approval_status="Approved"; employee_advance.save(ignore_permissions=True); employee_advance.submit(ignore_permissions=True)
        with session_as(maker):
            jurisdiction=new_doc("Payroll Tax Jurisdiction",jurisdiction_code="NG",jurisdiction_name="Nigeria",country_code="NG",currency="NGN",tax_year_start_month=1,tax_year_start_day=1,enabled=1).insert(ignore_permissions=True)
            tax_rule=new_doc("Payroll Tax Rule",rule_code="NG-PAYE-2026",rule_name="Nigeria PAYE 2026 Test Rule",jurisdiction=jurisdiction.name,effective_from=date(year,1,1),calculation_basis="Annualised Period Income",bands=[{"band_sequence":1,"lower_limit":0,"rate":10}],annual_relief=0,rounding_precision=2,approval_status="Pending",version=1).insert(ignore_permissions=True)
        with session_as(manager):
            tax_rule=get_doc("Payroll Tax Rule",tax_rule.name,ignore_permissions=True); tax_rule.approval_status="Approved"; tax_rule.save(ignore_permissions=True); tax_rule.submit(ignore_permissions=True)
        with session_as(maker):
            tax_profile=new_doc("Employee Tax Profile",employee=employee.name,jurisdiction=jurisdiction.name,tax_rule=tax_rule.name,effective_from=date(year,1,1),annual_relief=0,tax_exempt=0,approval_status="Pending").insert(ignore_permissions=True)
        with session_as(manager):
            tax_profile=get_doc("Employee Tax Profile",tax_profile.name,ignore_permissions=True); tax_profile.approval_status="Approved"; tax_profile.save(ignore_permissions=True); tax_profile.submit(ignore_permissions=True)
        with session_as(maker):
            basic=new_doc("Salary Component",component_code="BASIC",component_name="Basic Salary",component_type="Earning",calculation_type="Fixed",amount=1000,sequence=1,taxable=1,account=salary_expense.name).insert(ignore_permissions=True)
            bonus=new_doc("Salary Component",component_code="BONUS",component_name="Performance Bonus",component_type="Earning",calculation_type="Formula",formula="bonus * 1",input_fieldname="bonus",input_location="Salary Slip",sequence=2,taxable=1,account=salary_expense.name).insert(ignore_permissions=True)
            tax=new_doc("Salary Component",component_code="PAYE",component_name="PAYE",component_type="Deduction",calculation_type="Progressive Tax",tax_rule=tax_rule.name,periods_per_year=12,sequence=3,account=tax_payable.name).insert(ignore_permissions=True)
            loan_recovery=new_doc("Salary Component",component_code="LOAN_REC",component_name="Loan Repayment",component_type="Loan Repayment",calculation_type="Fixed",amount=50,sequence=4,account=loan.name).insert(ignore_permissions=True)
            advance_recovery=new_doc("Salary Component",component_code="ADV_REC",component_name="Advance Recovery",component_type="Advance Recovery",calculation_type="Fixed",amount=25,sequence=5,account=advance.name).insert(ignore_permissions=True)
            structure=new_doc("Salary Structure",structure_name="Monthly Staff",pay_frequency="Monthly",currency="NGN",components=[{"salary_component":basic.name},{"salary_component":bonus.name},{"salary_component":tax.name},{"salary_component":loan_recovery.name},{"salary_component":advance_recovery.name}],approval_status="Pending").insert(ignore_permissions=True)
            payroll_input=new_doc("Payroll Input",employee=employee.name,salary_component=bonus.name,input_fieldname="bonus",input_value=100,effective_from=date(year,11,1),effective_to=date(year,11,30),input_frequency="One-time",input_mode="Replace",approval_status="Pending").insert(ignore_permissions=True)
        with session_as(manager):
            payroll_input=get_doc("Payroll Input",payroll_input.name,ignore_permissions=True); payroll_input.approval_status="Approved"; payroll_input.save(ignore_permissions=True); payroll_input.submit(ignore_permissions=True)
        assert {r.component_code for r in structure.earnings}=={"BASIC","BONUS"} and "PAYE" in {r.component_code for r in structure.deductions}
        assert len(structure.components)==len(structure.earnings)+len(structure.deductions)
        with session_as(manager):
            structure=get_doc("Salary Structure",structure.name,ignore_permissions=True); structure.approval_status="Approved"; structure.save(ignore_permissions=True); structure.submit(ignore_permissions=True)
        employee.gross_pay = 1500; employee.save(ignore_permissions=True)                       # the employee's agreed total, kept apart from Base Salary
        import pytest
        with session_as(maker):
            with pytest.raises(Exception, match="cannot be more than"):
                new_doc("Salary Structure Assignment",employee=employee.name,salary_structure=structure.name,effective_from=date(year,1,1),base_salary=1600,currency="NGN",status="Draft",approval_status="Pending").insert(ignore_permissions=True)
        with session_as(maker):
            assignment=new_doc("Salary Structure Assignment",employee=employee.name,salary_structure=structure.name,effective_from=date(year,1,1),base_salary=1000,currency="NGN",status="Draft",approval_status="Pending").insert(ignore_permissions=True)
        assert assignment.gross_pay == 1500 and assignment.base_salary == 1000          # shown beside, never added to, the basic salary
        with session_as(manager):
            assignment=get_doc("Salary Structure Assignment",assignment.name,ignore_permissions=True); assignment.approval_status="Approved"; assignment.save(ignore_permissions=True); assignment.submit(ignore_permissions=True)
        with session_as(maker):
            run=new_doc("Payroll Run",run_title="November Payroll",pay_frequency="Monthly",period_start=date(year,11,1),period_end=date(year,11,30),posting_date=today,currency="NGN",payroll_payable_account=salary_payable.name,employees=[{"employee":employee.name,"salary_assignment":assignment.name,"loan_recovery_allocations":[{"employee_loan":employee_loan.name,"amount":"50"}],"advance_recovery_allocations":[{"employee_advance":employee_advance.name,"amount":"25"}]}],approval_status="Pending").insert(ignore_permissions=True)
        assert run.total_gross==Decimal("1100.00") and run.total_net_pay==Decimal("915.00")
        slip_draft=get_doc("Salary Slip",run.employees[0].salary_slip,ignore_permissions=True)
        assert slip_draft.docstatus==0 and slip_draft.status=="Draft"
        with session_as(maker):
            slip_draft.bonus=150; slip_draft.save(ignore_permissions=True)
            run=get_doc("Payroll Run",run.name,ignore_permissions=True); run.save(ignore_permissions=True)
        assert run.total_gross==Decimal("1150.00") and run.total_net_pay==Decimal("960.00")
        refreshed_slip=get_doc("Salary Slip",run.employees[0].salary_slip,ignore_permissions=True)
        assert any(x.component_code=="BONUS" and x.amount==Decimal("150.00") for x in refreshed_slip.lines)
        with session_as(manager):
            run=get_doc("Payroll Run",run.name,ignore_permissions=True); run.approval_status="Approved"; run.save(ignore_permissions=True); run.submit(ignore_permissions=True)
        run=get_doc("Payroll Run",run.name,ignore_permissions=True)
        assert run.status=="Posted" and run.posting_batch
        slip=get_doc("Salary Slip",run.employees[0].salary_slip,ignore_permissions=True)
        assert slip.docstatus==1 and slip.outstanding_amount==Decimal("960.00")
        assert any(x.component_code=="BONUS" and x.amount==Decimal("150.00") for x in slip.lines)
        assert any(x["component_code"]=="PAYE" and Decimal(x["period_tax"])==Decimal("115.00") for x in slip.tax_computation)
        assert get_doc("Payroll Input",payroll_input.name,ignore_permissions=True).status=="Processed"
        assert get_account_balance(salary_expense.name)==Decimal("1150.000000")
        assert get_account_balance(tax_payable.name)==Decimal("-115.000000")
        assert get_account_balance(loan.name,party_type="Employee",party=employee.name)==Decimal("1150.000000")
        assert get_account_balance(advance.name,party_type="Employee",party=employee.name)==Decimal("275.000000")
        assert get_account_balance(salary_payable.name,party_type="Employee",party=employee.name)==Decimal("-960.000000")
        loan_after=get_doc("Employee Loan",employee_loan.name,ignore_permissions=True)
        assert loan_after.outstanding_principal==Decimal("1150.00")
        assert loan_after.schedule[0].paid_principal==Decimal("50.00") and loan_after.schedule[0].status=="Partially Paid"
        assert get_doc("Employee Advance",employee_advance.name,ignore_permissions=True).outstanding_amount==Decimal("275.00")
        with session_as(maker):
            payment=new_doc("Payroll Payment",payment_date=today,currency="NGN",lines=[{"salary_slip":slip.name,"amount":960,"bank_account":bank.name}],approval_status="Pending").insert(ignore_permissions=True)
        with session_as(manager):
            payment=get_doc("Payroll Payment",payment.name,ignore_permissions=True); payment.approval_status="Approved"; payment.save(ignore_permissions=True); payment.submit(ignore_permissions=True)
        slip=get_doc("Salary Slip",slip.name,ignore_permissions=True)
        assert slip.status=="Paid" and slip.outstanding_amount==Decimal("0.00")
        assert get_account_balance(bank.name)==Decimal("-2460.000000")
        assert get_account_balance(salary_payable.name,party_type="Employee",party=employee.name)==Decimal("0.000000")
        from velora_erp.finance.reconciliation_adapters import reconcile_employee_finance
        employee_recs=reconcile_employee_finance(as_of_date=today)
        assert employee_recs and all(x["status"]=="Reconciled" for x in employee_recs)
        from velora_erp.finance.report.payroll_register.payroll_register import execute as payroll_register
        from velora_erp.finance.report.employee_loan_register.employee_loan_register import execute as loan_register
        from velora_erp.finance.report.employee_advance_register.employee_advance_register import execute as advance_register
        assert sum(r.type=="data" for r in payroll_register({"to_date":today}).rows)==1
        assert sum(r.type=="data" for r in loan_register({"employee":employee.name}).rows)==1
        # ---------- cancel: newest first
        import pytest
        from velora.exceptions import ValidationError
        with session_as(manager):
            with pytest.raises(ValidationError, match="paid|Payroll Payment"):
                get_doc("Payroll Run", run.name, ignore_permissions=True).cancel(reason="x")
            pay = get_doc("Payroll Payment", payment.name, ignore_permissions=True); pay.cancel(reason="Wrong bank", ignore_permissions=True)
        slip = get_doc("Salary Slip", slip.name, ignore_permissions=True)
        assert slip.status == "Posted" and slip.outstanding_amount == Decimal("960.00") and slip.paid_amount == Decimal("0")
        assert get_account_balance(bank.name) == Decimal("-1500.000000")
        assert get_account_balance(salary_payable.name, party_type="Employee", party=employee.name) == Decimal("-960.000000")
        with session_as(manager):
            get_doc("Payroll Run", run.name, ignore_permissions=True).cancel(reason="Wrong inputs", ignore_permissions=True)
        run = get_doc("Payroll Run", run.name, ignore_permissions=True)
        assert run.docstatus == 2 and run.status == "Cancelled"
        assert get_doc("Salary Slip", slip.name, ignore_permissions=True).docstatus == 2
        assert get_doc("Payroll Input", payroll_input.name, ignore_permissions=True).status != "Processed"
        assert get_account_balance(salary_expense.name) == Decimal("0.000000") and get_account_balance(tax_payable.name) == Decimal("0.000000")
        assert get_account_balance(salary_payable.name, party_type="Employee", party=employee.name) == Decimal("0.000000")
        loan_back = get_doc("Employee Loan", employee_loan.name, ignore_permissions=True)
        assert loan_back.outstanding_principal == Decimal("1200.00") and loan_back.schedule[0].paid_principal in (None, Decimal("0"), Decimal("0.00"))
        assert loan_back.schedule[0].status in (None, "Pending")
        assert get_doc("Employee Advance", employee_advance.name, ignore_permissions=True).outstanding_amount == Decimal("300.00")
        assert get_account_balance(loan.name, party_type="Employee", party=employee.name) == Decimal("1200.000000")
        assert get_account_balance(advance.name, party_type="Employee", party=employee.name) == Decimal("300.000000")
        # a loan with nothing recovered can now be cancelled; the advance too
        with session_as(manager):
            get_doc("Employee Loan", employee_loan.name, ignore_permissions=True).cancel(reason="Wrong employee", ignore_permissions=True)
            get_doc("Employee Advance", employee_advance.name, ignore_permissions=True).cancel(reason="Wrong employee", ignore_permissions=True)
        assert get_account_balance(loan.name, party_type="Employee", party=employee.name) == Decimal("0.000000")
    finally:
        velora.shutdown()
