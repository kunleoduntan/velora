from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc
from velora.exceptions import ValidationError
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.party_accounting import get_party_balances, reconcile_party_control_account
from velora_erp.setup import after_install


def setup(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path / 'party-masters.db'}", apps=["velora_erp"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    year=date.today().year
    new_doc("Financial Year", year_name=f"FY-{year}", start_date=date(year,1,1), end_date=date(year,12,31), status="Open", is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period", period_name=f"FY-{year}-P01", financial_year=f"FY-{year}", period_number=1, start_date=date(year,1,1), end_date=date(year,12,31), status="Open").insert(ignore_permissions=True)
    for code,label,root in (("A","Assets","Asset"),("L","Liabilities","Liability"),("E","Equity","Equity")):
        new_doc("Account Group",group_code=code,group_name=label,root_type=root,is_group=0).insert(ignore_permissions=True)
    ar=new_doc("Account",account_code="1100",account_name="Trade Receivables",account_group="A",account_type="RECEIVABLE",is_control_account=1,control_account_type="Receivables").insert(ignore_permissions=True)
    ap=new_doc("Account",account_code="2100",account_name="Trade Payables",account_group="L",account_type="PAYABLE",is_control_account=1,control_account_type="Payables").insert(ignore_permissions=True)
    equity=new_doc("Account",account_code="3000",account_name="Capital",account_group="E",account_type="EQUITY").insert(ignore_permissions=True)
    new_doc("Customer Group",group_code="CORP",group_name="Corporate",is_group=0).insert(ignore_permissions=True)
    new_doc("Supplier Group",group_code="LOCAL",group_name="Local Suppliers",is_group=0).insert(ignore_permissions=True)
    return ar,ap,equity


def test_customer_supplier_master_validation_and_party_balances(tmp_path):
    ar,ap,equity=setup(tmp_path)
    try:
        terms=new_doc("Payment Terms",terms_code="N30",terms_name="Net 30",due_days=30).insert(ignore_permissions=True)
        customer=new_doc("Customer",customer_code="C001",customer_name="Acme Limited",customer_group="CORP",customer_type="Company",control_account=ar.name,payment_terms=terms.name,currency="NGN",credit_limit="500000").insert(ignore_permissions=True)
        supplier=new_doc("Supplier",supplier_code="S001",supplier_name="Supply Limited",supplier_group="LOCAL",supplier_type="Company",control_account=ap.name,payment_terms=terms.name,currency="NGN").insert(ignore_permissions=True)
        assert customer.name=="C001" and supplier.name=="S001"
        with pytest.raises(ValidationError,match="must be an Asset"):
            new_doc("Customer",customer_code="C002",customer_name="Wrong Account",customer_group="CORP",customer_type="Company",control_account=ap.name).insert(ignore_permissions=True)
        with pytest.raises(ValidationError,match="negative"):
            new_doc("Customer",customer_code="C003",customer_name="Bad Limit",customer_group="CORP",customer_type="Company",control_account=ar.name,credit_limit=-1).insert(ignore_permissions=True)
        post_financial_transaction(source_doctype="Test Source",source_name="CUSTOMER-POST-1",posting_date=date.today(),currency="NGN",lines=[
            {"account":ar.name,"debit":1250,"credit":0,"party_type":"Customer","party":customer.name},
            {"account":equity.name,"debit":0,"credit":1250},
        ])
        balances=get_party_balances("Customer",customer.name,as_of=date.today())
        assert len(balances)==1 and Decimal(str(balances[0]["balance"]))==Decimal("1250.000000")
        result=reconcile_party_control_account(ar.name,"Customer")
        assert result["is_reconciled"] is True
        assert result["difference"] == Decimal("0")
    finally:
        velora.shutdown()


def test_customer_statement_report_is_party_scoped(tmp_path):
    ar,ap,equity=setup(tmp_path)
    try:
        from velora import new_doc
        from velora.reporting.runner import run_report
        customer=new_doc("Customer",customer_code="C004",customer_name="Statement Customer",customer_group="CORP",customer_type="Company",control_account=ar.name).insert(ignore_permissions=True)
        post_financial_transaction(source_doctype="Test Source",source_name="STATEMENT-1",posting_date=date.today(),currency="NGN",lines=[
            {"account":ar.name,"debit":75,"credit":0,"party_type":"Customer","party":customer.name},
            {"account":equity.name,"debit":0,"credit":75},
        ])
        report=run_report("Customer Statement",{"customer":customer.name,"from_date":date.today().replace(month=1,day=1).isoformat(),"to_date":date.today().isoformat()})
        assert report.title.endswith(customer.name)
        assert any(row.values.get("balance")==Decimal("75.000000") for row in report.rows)
        ledger_report=run_report("Customer Ledger",{"customer":customer.name,"from_date":date.today().replace(month=1,day=1).isoformat(),"to_date":date.today().isoformat()})
        assert ledger_report.title.endswith(customer.name)
    finally:
        velora.shutdown()


def test_supplier_statement_and_payables_reconciliation(tmp_path):
    ar,ap,equity=setup(tmp_path)
    try:
        from velora.reporting.runner import run_report
        supplier=new_doc("Supplier",supplier_code="S002",supplier_name="Statement Supplier",supplier_group="LOCAL",supplier_type="Company",control_account=ap.name).insert(ignore_permissions=True)
        post_financial_transaction(source_doctype="Test Source",source_name="SUPPLIER-POST-1",posting_date=date.today(),currency="NGN",lines=[
            {"account":equity.name,"debit":90,"credit":0},
            {"account":ap.name,"debit":0,"credit":90,"party_type":"Supplier","party":supplier.name},
        ])
        # Supplier balances are credit-normal, so the ledger's net-debit sign is negative for a payable.
        from velora_erp.finance.party_accounting import get_party_balances
        balances=get_party_balances("Supplier",supplier.name,as_of=date.today())
        assert Decimal(str(balances[0]["balance"])) == Decimal("-90.000000")
        report=run_report("Supplier Statement",{"supplier":supplier.name,"from_date":date.today().replace(month=1,day=1).isoformat(),"to_date":date.today().isoformat()})
        assert report.title.endswith(supplier.name)
        ledger_report=run_report("Supplier Ledger",{"supplier":supplier.name,"from_date":date.today().replace(month=1,day=1).isoformat(),"to_date":date.today().isoformat()})
        assert ledger_report.title.endswith(supplier.name)
        reconciliation=reconcile_party_control_account(ap.name,"Supplier")
        assert reconciliation["is_reconciled"] is True
    finally:
        velora.shutdown()


def test_employee_ledger_supports_employee_asset_and_liability_accounts(tmp_path):
    ar, ap, equity = setup(tmp_path)
    try:
        from velora.reporting.runner import run_report
        employee = new_doc(
            "Employee", employee_code="E001", employee_name="Ada Employee",
            employee_type="Permanent", advance_account=ar.name,
            default_payable_account=ap.name,
        ).insert(ignore_permissions=True)
        post_financial_transaction(
            source_doctype="Test Source", source_name="ADV-001",
            posting_date=date.today(), currency="NGN",
            lines=[
                {"account": ar.name, "debit": 25000, "credit": 0,
                 "party_type": "Employee", "party": employee.name,
                 "transaction_date": date.today(), "external_reference": "BANK-REF-01",
                 "line_description": "Staff travel advance"},
                {"account": equity.name, "debit": 0, "credit": 25000,
                 "line_description": "Advance funding"},
            ],
        )
        balances = get_party_balances("Employee", employee.name, as_of=date.today())
        assert len(balances) == 1
        assert Decimal(str(balances[0]["balance"])) == Decimal("25000.000000")
        post_financial_transaction(
            source_doctype="Test Source", source_name="EMP-PAY-001",
            posting_date=date.today(), currency="NGN",
            lines=[
                {"account": equity.name, "debit": 5000, "credit": 0},
                {"account": ap.name, "debit": 0, "credit": 5000,
                 "party_type": "Employee", "party": employee.name,
                 "line_description": "Approved employee reimbursement"},
            ],
        )
        balances = get_party_balances("Employee", employee.name, as_of=date.today())
        assert len(balances) == 2
        assert {Decimal(str(item["balance"])) for item in balances} == {Decimal("25000.000000"), Decimal("-5000.000000")}
        report = run_report("Employee Ledger", {
            "employee": employee.name,
            "from_date": date.today().replace(month=1, day=1).isoformat(),
            "to_date": date.today().isoformat(),
        })
        assert report.title.endswith(employee.name)
        assert any(row.values.get("source") == "Test Source ADV-001" for row in report.rows)
        assert any(row.values.get("source") == "Test Source EMP-PAY-001" for row in report.rows)
        reconciliation = reconcile_party_control_account(ar.name, "Employee")
        assert reconciliation["is_reconciled"] is True
        payable_reconciliation = reconcile_party_control_account(ap.name, "Employee")
        assert payable_reconciliation["is_reconciled"] is True
    finally:
        velora.shutdown()
