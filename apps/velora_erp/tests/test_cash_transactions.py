from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.finance.engine import get_account_balance
from velora_erp.setup import after_install

MAKER = Session("cash-maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("cash-approver@example.test", frozenset({"Finance Manager"}))


def setup_cash(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'cash.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    today = date.today(); year = today.year
    new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year,1,1), end_date=date(year,12,31), status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-P01", financial_year=f"FY-{year}", period_number=1, start_date=date(year,1,1), end_date=date(year,12,31), status="Open").insert(ignore_permissions=True)
    groups={}
    for code,label,root in [("A","Assets","Asset"),("L","Liabilities","Liability"),("E","Equity","Equity"),("I","Income","Income"),("X","Expense","Expense")]:
        groups[code]=new_doc("Account Group",group_code=code,group_name=label,root_type=root,is_group=0).insert(ignore_permissions=True)
    accounts={}
    for code,name,group,kind,extra in [
        ("1000","Main Bank","A","BANK",{"is_control_account":1,"control_account_type":"Bank"}),
        ("1100","Trade Receivables","A","RECEIVABLE",{"is_control_account":1,"control_account_type":"Receivables","requires_party":1}),
        ("2100","Trade Payables","L","PAYABLE",{"is_control_account":1,"control_account_type":"Payables","requires_party":1}),
        ("2200","Customer Advances","L","CUSTOMER_ADVANCE",{}),
        ("1200","Supplier Advances","A","SUPPLIER_ADVANCE",{}),
        ("3000","Capital","E","EQUITY",{}),
        ("4000","Other Income","I","REVENUE",{}),
        ("5000","Office Expense","X","OPERATING_EXPENSE",{}),
    ]:
        accounts[code]=new_doc("Account",account_code=code,account_name=name,account_group=group,account_type=kind,allow_manual_posting=1,**extra).insert(ignore_permissions=True)
    new_doc("Customer Group",group_code="CG",group_name="Customers",is_group=0).insert(ignore_permissions=True)
    new_doc("Supplier Group",group_code="SG",group_name="Suppliers",is_group=0).insert(ignore_permissions=True)
    customer=new_doc("Customer",customer_code="C001",customer_name="Acme",customer_group="CG",customer_type="Company",control_account=accounts["1100"].name,advance_account=accounts["2200"].name).insert(ignore_permissions=True)
    supplier=new_doc("Supplier",supplier_code="S001",supplier_name="Supply Co",supplier_group="SG",supplier_type="Company",control_account=accounts["2100"].name,advance_account=accounts["1200"].name).insert(ignore_permissions=True)
    return accounts,customer,supplier


def approve(doc):
    with session_as(APPROVER):
        doc=get_doc(doc.doctype,doc.name)
        doc.approval_status="Approved"; doc.save(ignore_permissions=True)
        doc.submit(ignore_permissions=True); doc.reload()
    return doc


def test_customer_receipt_posts_to_customer_subledger_once(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            receipt=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Customer Receipt",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Customer settlement",lines=[{"account":accounts["1100"].name,"amount":1250,"party_type":"Customer","party":customer.name,"description":"Invoice settlement"}]).insert()
        receipt=approve(receipt)
        assert receipt.docstatus==1 and receipt.posting_batch
        assert get_account_balance(accounts["1000"].name)==Decimal("1250.000000")
        assert get_account_balance(accounts["1100"].name)==Decimal("-1250.000000")
        from velora_erp.finance.party_accounting import get_party_balances
        assert Decimal(str(get_party_balances("Customer",customer.name,as_of=date.today())[0]["balance"])) == Decimal("-1250.000000")
    finally:
        velora.shutdown()


def test_supplier_payment_posts_payable_and_bank_entries(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=date.today(),posting_date=date.today(),purpose="Supplier Payment",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Supplier settlement",lines=[{"account":accounts["2100"].name,"amount":500,"party_type":"Supplier","party":supplier.name,"description":"Supplier invoice settlement"}]).insert()
        payment=approve(payment)
        assert payment.docstatus==1 and payment.posting_batch
        assert get_account_balance(accounts["1000"].name)==Decimal("-500.000000")
        assert get_account_balance(accounts["2100"].name)==Decimal("500.000000")
    finally:
        velora.shutdown()


def test_other_income_receipt_does_not_require_customer_or_supplier(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            receipt=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Other Income",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Miscellaneous income",lines=[{"account":accounts["4000"].name,"amount":300,"description":"Interest received"}]).insert()
        approve(receipt)
        assert get_account_balance(accounts["1000"].name)==Decimal("300.000000")
        assert get_account_balance(accounts["4000"].name)==Decimal("-300.000000")
    finally:
        velora.shutdown()


def test_expense_payment_uses_beneficiary_without_supplier(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=date.today(),posting_date=date.today(),purpose="Expense Payment",beneficiary="Office landlord",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Office expense paid to beneficiary",lines=[{"account":accounts["5000"].name,"amount":125,"description":"Payee: Office landlord"}]).insert()
        approve(payment)
        assert get_account_balance(accounts["5000"].name)==Decimal("125.000000")
        assert get_account_balance(accounts["1000"].name)==Decimal("-125.000000")
    finally:
        velora.shutdown()


def test_cash_transaction_requires_independent_approval_and_rejects_wrong_control_account(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            with pytest.raises(ValidationError,match="Receivables Control Account"):
                new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Customer Receipt",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Wrong account",lines=[{"account":accounts["2100"].name,"amount":10,"party_type":"Customer","party":customer.name}]).insert()
            good=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Other Income",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Needs approval",lines=[{"account":accounts["4000"].name,"amount":10}]).insert()
            from wf_helpers import install_approval; install_approval("Receipt")
            good=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Other Income",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Needs approval",lines=[{"account":accounts["4000"].name,"amount":10}]).insert()
            with pytest.raises(ValidationError,match="approval workflow"):
                good.submit(ignore_permissions=True)
        assert get_account_balance(accounts["1000"].name)==Decimal("0")
    finally:
        velora.shutdown()


def test_customer_receipt_supports_withholding_tax_and_reports_net_cash(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        from velora_erp.finance.party_accounting import get_party_balances
        wht=new_doc("Account",account_code="1300",account_name="WHT Receivable",account_group="A",account_type="CLEARING",allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            receipt=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Customer Receipt",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Gross invoice settlement with WHT",lines=[
                {"account":accounts["1100"].name,"entry_side":"Credit","amount":1000,"party_type":"Customer","party":customer.name,"description":"Gross customer settlement"},
                {"account":wht.name,"entry_side":"Debit","amount":50,"description":"Withholding tax deducted"},
            ]).insert()
        receipt=approve(receipt)
        assert receipt.total_amount==Decimal("950")
        assert receipt.total_accounting_amount==Decimal("1000")
        assert get_account_balance(accounts["1000"].name)==Decimal("950.000000")
        assert get_account_balance(accounts["1100"].name)==Decimal("-1000.000000")
        assert get_account_balance(wht.name)==Decimal("50.000000")
        assert Decimal(str(get_party_balances("Customer",customer.name,as_of=date.today())[0]["balance"]))==Decimal("-1000.000000")
    finally:
        velora.shutdown()


def test_prepayment_schedule_generates_monthly_ledger_recognition(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        prepaid=new_doc("Account",account_code="1400",account_name="Prepaid Insurance",account_group="A",account_type="PREPAYMENT",allow_manual_posting=1).insert(ignore_permissions=True)
        expense=new_doc("Account",account_code="5100",account_name="Insurance Expense",account_group="X",account_type="OPERATING_EXPENSE",allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=date.today(),posting_date=date.today(),purpose="Prepayment",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Annual insurance premium",lines=[{"account":prepaid.name,"amount":1200,"description":"Annual insurance"}]).insert()
        payment=approve(payment)
        with session_as(MAKER):
            schedule=new_doc("Recognition Schedule",schedule_type="Prepayment",source_doctype="Payment",source_document=payment.name,start_date=date.today(),period_count=3,total_amount=1200,balance_account=prepaid.name,recognition_account=expense.name).insert()
        schedule=approve(schedule)
        from velora_erp.finance.recognition.schedules import process_due_recognitions
        created=process_due_recognitions(as_of_date=date.today())
        assert len(created)==1
        assert get_account_balance(expense.name)==Decimal("400.000000")
        assert get_account_balance(prepaid.name)==Decimal("800.000000")
        assert process_due_recognitions(as_of_date=date.today())==[]
    finally:
        velora.shutdown()


def test_supplier_payment_supports_withholding_deduction(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        wht=new_doc("Account",account_code="2250",account_name="WHT Payable",account_group="L",account_type="WITHHOLDING_TAX",allow_manual_posting=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=date.today(),posting_date=date.today(),purpose="Supplier Payment",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Supplier paid net of WHT",lines=[
                {"account":accounts["2100"].name,"entry_side":"Debit","amount":1000,"party_type":"Supplier","party":supplier.name,"description":"Gross supplier settlement"},
                {"account":wht.name,"entry_side":"Credit","amount":50,"description":"Withholding tax deducted"},
            ]).insert()
        payment=approve(payment)
        assert payment.total_amount==Decimal("950")
        assert payment.total_accounting_amount==Decimal("1000")
        assert get_account_balance(accounts["1000"].name)==Decimal("-950.000000")
        assert get_account_balance(accounts["2100"].name)==Decimal("1000.000000")
        assert get_account_balance(wht.name)==Decimal("-50.000000")
    finally:
        velora.shutdown()


def test_deferred_income_schedule_recognises_income_over_months(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        deferred=new_doc("Account",account_code="2300",account_name="Deferred Income",account_group="L",account_type="ACCRUAL",allow_manual_posting=1).insert(ignore_permissions=True)
        income=accounts["4000"]
        with session_as(MAKER):
            receipt=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Deferred Income",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Annual service contract received in advance",lines=[{"account":deferred.name,"amount":900,"description":"Service contract advance"}]).insert()
        receipt=approve(receipt)
        with session_as(MAKER):
            schedule=new_doc("Recognition Schedule",schedule_type="Deferred Income",source_doctype="Receipt",source_document=receipt.name,start_date=date.today(),period_count=3,total_amount=900,balance_account=deferred.name,recognition_account=income.name).insert()
        schedule=approve(schedule)
        from velora_erp.finance.recognition.schedules import process_due_recognitions
        created=process_due_recognitions(as_of_date=date.today())
        assert len(created)==1
        assert get_account_balance(deferred.name)==Decimal("-600.000000")
        assert get_account_balance(income.name)==Decimal("-300.000000")
    finally:
        velora.shutdown()


def test_customer_and_supplier_advances_use_party_tracked_balance_sheet_accounts(tmp_path):
    accounts,customer,supplier=setup_cash(tmp_path)
    try:
        with session_as(MAKER):
            receipt=new_doc("Receipt",receipt_date=date.today(),posting_date=date.today(),purpose="Customer Advance",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Customer deposit",lines=[{"account":accounts["2200"].name,"amount":600,"party_type":"Customer","party":customer.name}]).insert()
        approve(receipt)
        assert get_account_balance(accounts["2200"].name)==Decimal("-600.000000")
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=date.today(),posting_date=date.today(),purpose="Supplier Advance",currency="NGN",exchange_rate=1,cash_account=accounts["1000"].name,narration="Advance to supplier",lines=[{"account":accounts["1200"].name,"amount":250,"party_type":"Supplier","party":supplier.name}]).insert()
        approve(payment)
        assert get_account_balance(accounts["1200"].name)==Decimal("250.000000")
        from velora_erp.finance.party_accounting import get_party_balances
        assert Decimal(str(get_party_balances("Customer",customer.name,as_of=date.today())[0]["balance"]))==Decimal("-600.000000")
        assert Decimal(str(get_party_balances("Supplier",supplier.name,as_of=date.today())[0]["balance"]))==Decimal("250.000000")
    finally:
        velora.shutdown()
