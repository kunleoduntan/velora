from datetime import date, timedelta
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.permissions import Session, session_as
from velora.exceptions import ValidationError
from velora_erp.setup import after_install
from velora_erp.finance.engine import get_account_balance

MAKER = Session("ops-maker@example.test", frozenset({"Accountant"}))
APPROVER = Session("ops-approver@example.test", frozenset({"Finance Manager"}))

def setup_ops(tmp_path):
    today=date.today()
    velora.configure(db_url=f"sqlite:///{tmp_path / 'ops.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    new_doc("Financial Year",year_name=f"FY-{today.year}",start_date=date(today.year,1,1),end_date=date(today.year,12,31),status="Open",is_current=1).insert(ignore_permissions=True)
    new_doc("Financial Period",period_name=f"FY-{today.year}-P01",financial_year=f"FY-{today.year}",period_number=1,start_date=date(today.year,1,1),end_date=date(today.year,12,31),status="Open").insert(ignore_permissions=True)
    groups={}
    for code,label,root in [("A","Assets","Asset"),("L","Liabilities","Liability"),("E","Equity","Equity"),("I","Income","Income"),("X","Expense","Expense")]:
        groups[code]=new_doc("Account Group",group_code=code,group_name=label,root_type=root,is_group=0).insert(ignore_permissions=True)
    accounts={}
    for code,name,g,kind,extra in [
        ("1000","Main Bank","A","BANK",{"is_control_account":1,"control_account_type":"Bank"}),
        ("1500","Office Equipment Cost","A","FIXED_ASSET",{}),
        ("1590","Accumulated Depreciation","A","ACCUM_DEPRECIATION",{}),
        ("2200","Accrued Liability","L","ACCRUAL",{}),
        ("1600","Right of Use Asset","A","FIXED_ASSET",{}),
        ("1690","ROU Accumulated Depreciation","A","ACCUM_DEPRECIATION",{}),
        ("2100","Trade Payables","L","PAYABLE",{"is_control_account":1,"control_account_type":"Payables","requires_party":1}),
        ("2300","Lease Liability","L","ACCRUAL",{}),
        ("3000","Revaluation Reserve","E","EQUITY",{}),
        ("4000","Other Income","I","REVENUE",{}),
        ("4100","Revaluation Gain","I","REVENUE",{}),
        ("5000","Office Expense","X","OPERATING_EXPENSE",{}),
        
        ("5200","Lease Interest","X","OPERATING_EXPENSE",{}),
        ("5300","Revaluation Loss","X","OPERATING_EXPENSE",{}),
        ("5400","Depreciation Expense","X","OPERATING_EXPENSE",{}),
    ]:
        accounts[code]=new_doc("Account",account_code=code,account_name=name,account_group=groups[g].name,account_type=kind,allow_manual_posting=1,**extra).insert(ignore_permissions=True)
    from velora.application_workspaces import listing
    workspace_names={row["name"] for row in listing() if row.get("scope")=="company"}
    assert {"Treasury","Fixed Assets"} <= workspace_names
    new_doc("Supplier Group",group_code="SG",group_name="Suppliers",is_group=0).insert(ignore_permissions=True)
    supplier=new_doc("Supplier",supplier_code="SUP-01",supplier_name="Asset Supplier",supplier_group="SG",supplier_type="Company",control_account=accounts["2100"].name).insert(ignore_permissions=True)
    category=new_doc("Fixed Asset Category",category_name="Office Equipment",asset_account=accounts["1500"].name,accumulated_depreciation_account=accounts["1590"].name,depreciation_expense_account=accounts["5400"].name,default_useful_life_months=60).insert(ignore_permissions=True)
    return accounts,supplier,category

def approve_submit(doc):
    with session_as(APPROVER):
        d=get_doc(doc.doctype,doc.name); d.approval_status="Approved"; d.save(ignore_permissions=True); d.submit(ignore_permissions=True); d.reload()
    return d

def test_batch_bank_transaction_and_csv_processor_create_approved_postings(tmp_path):
    accounts,supplier,category=setup_ops(tmp_path)
    try:
        with session_as(APPROVER):
            new_doc("Bank Transaction Coding Rule",priority=10,match_field="Description",match_operator="Contains",match_text="pos settlement",direction="Receipt",offset_account=accounts["4000"].name).insert()
            new_doc("Bank Transaction Coding Rule",priority=10,match_field="Description",match_operator="Contains",match_text="bank fee",direction="Payment",offset_account=accounts["5000"].name).insert()
        with session_as(MAKER):
            processor=new_doc("Bank Transaction Processor",bank_account=accounts["1000"].name,statement_date_from=date.today(),statement_date_to=date.today(),currency="NGN",exchange_rate=1,import_reference="STMT-001",raw_csv_data="transaction_date,direction,description,bank_reference,amount,offset_account\n"+f"{date.today()},Receipt,POS settlement,REF-001,250.00,\n"+f"{date.today()},Payment,Monthly bank fee,REF-002,50.00,\n").insert()
            assert processor.exception_count==0
            assert processor.transactions[0].offset_account==accounts["4000"].name
            assert processor.transactions[1].offset_account==accounts["5000"].name
            processor.submit(ignore_permissions=True)
        batch=get_doc("Batch Bank Transaction",processor.generated_batch,ignore_permissions=True)
        assert batch.docstatus==0 and batch.approval_status=="Approved"      # no approval workflow in this company
        approve_submit(batch)
        assert get_account_balance(accounts["1000"].name)==Decimal("200.000000")
        assert get_account_balance(accounts["4000"].name)==Decimal("-250.000000")
        assert get_account_balance(accounts["5000"].name)==Decimal("50.000000")
    finally:
        velora.shutdown()

def test_accrual_posts_and_reverses_on_due_date(tmp_path):
    accounts,supplier,category=setup_ops(tmp_path)
    try:
        with session_as(MAKER):
            accrual=new_doc("Accrual",reporting_date=date.today(),description="November utilities",currency="NGN",exchange_rate=1,auto_reverse=1,reversal_date=date.today()+timedelta(days=1),lines=[{"description":"Utilities incurred","expense_account":accounts["5000"].name,"accrued_liability_account":accounts["2200"].name,"amount":Decimal("1250.00")}]).insert()
        approve_submit(accrual)
        assert get_account_balance(accounts["5000"].name)==Decimal("1250.000000")
        from velora_erp.finance.doctype.accrual.accrual import process_due_accrual_reversals
        reversed_names=process_due_accrual_reversals(date.today()+timedelta(days=1))
        assert accrual.name in reversed_names
        assert get_account_balance(accounts["5000"].name)==Decimal("0.000000")
        refreshed=get_doc("Accrual",accrual.name,ignore_permissions=True)
        assert refreshed.status=="Reversed" and refreshed.reversal_batch
        from velora_erp.finance.engine import get_account_activity
        assert get_account_activity(accounts["5000"].name)
    finally:
        velora.shutdown()

def test_asset_request_purchase_revaluation_and_disposal(tmp_path):
    accounts,supplier,category=setup_ops(tmp_path)
    try:
        with session_as(MAKER):
            req=new_doc("Fixed Asset Request",request_date=date.today(),purpose="Replace office workstation",items=[{"description":"Workstation","asset_category":category.name,"quantity":1,"estimated_unit_cost":1000}]).insert()
        approve_submit(req)
        with session_as(MAKER):
            purchase=new_doc("Fixed Asset Purchase",purchase_date=date.today(),request_reference=req.name,purchase_type="Supplier Credit",supplier=supplier.name,supplier_payable_account=accounts["2100"].name,currency="NGN",exchange_rate=1,items=[{"asset_name":"Workstation 01","asset_category":category.name,"quantity":1,"unit_cost":1000,"asset_account":accounts["1500"].name,"useful_life_months":60,"residual_value":100}]).insert()
        purchase=approve_submit(purchase)
        asset_name=purchase.created_assets
        asset=get_doc("Fixed Asset",asset_name,ignore_permissions=True)
        assert asset.carrying_amount==Decimal("1000")
        asset.acquisition_cost=Decimal("5000")
        with pytest.raises(ValidationError, match="Protected asset financial fields"):
            asset.save(ignore_permissions=True)
        asset=get_doc("Fixed Asset",asset_name,ignore_permissions=True)
        with session_as(MAKER):
            reval=new_doc("Fixed Asset Revaluation",asset=asset.name,revaluation_date=date.today(),valuation_method="Market Comparable",new_carrying_amount=1200,revaluation_surplus_account=accounts["3000"].name,reason="Independent market valuation indicates higher value").insert()
        approve_submit(reval)
        asset=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
        assert asset.carrying_amount==Decimal("1200") and asset.revaluation_surplus==Decimal("200")
        with session_as(MAKER):
            reval_down=new_doc("Fixed Asset Revaluation",asset=asset.name,revaluation_date=date.today(),valuation_method="Market Comparable",new_carrying_amount=1150,revaluation_surplus_account=accounts["3000"].name,revaluation_loss_account=accounts["5300"].name,reason="Market correction").insert()
        approve_submit(reval_down)
        asset=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
        assert asset.carrying_amount==Decimal("1150") and asset.revaluation_surplus==Decimal("150")
        with session_as(MAKER):
            reval_loss=new_doc("Fixed Asset Revaluation",asset=asset.name,revaluation_date=date.today(),valuation_method="Market Comparable",new_carrying_amount=900,revaluation_surplus_account=accounts["3000"].name,revaluation_loss_account=accounts["5300"].name,reason="Further market correction").insert()
        approve_submit(reval_loss)
        asset=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
        assert asset.carrying_amount==Decimal("900") and asset.revaluation_surplus==Decimal("0") and asset.revaluation_loss_balance==Decimal("100")
        with session_as(MAKER):
            reval_reversal=new_doc("Fixed Asset Revaluation",asset=asset.name,revaluation_date=date.today(),valuation_method="Market Comparable",new_carrying_amount=950,revaluation_gain_account=accounts["4100"].name,reason="Partial reversal of prior loss").insert()
        approve_submit(reval_reversal)
        asset=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
        assert asset.carrying_amount==Decimal("950") and asset.revaluation_loss_balance==Decimal("50")
        with session_as(MAKER):
            disposal=new_doc("Fixed Asset Disposal",asset=asset.name,disposal_date=date.today(),disposal_type="Sale",disposal_proceeds=1000,disposal_costs=20,disposal_cost_account=accounts["5300"].name,disposal_cost_payment_account=accounts["1000"].name,proceeds_account=accounts["1000"].name,buyer="Secondary buyer",physical_verification_done=1,verified_by="Asset Manager",verification_date=date.today(),gain_account=accounts["4000"].name,loss_account=accounts["5300"].name,reason="Asset sold").insert()
        approve_submit(disposal)
        asset=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
        assert asset.status=="Disposed" and asset.carrying_amount==Decimal("0")
        assert disposal.gain_loss==Decimal("30")
    finally:
        velora.shutdown()

def test_lease_commencement_and_payment_schedule_settlement(tmp_path):
    accounts,supplier,category=setup_ops(tmp_path)
    try:
        start=date.today(); end=start+timedelta(days=365)
        due=start+timedelta(days=30)
        with session_as(MAKER):
            lease=new_doc("Fixed Asset Lease",lease_type="Lease In (Lessee)",asset_name="Office Printer ROU",asset_category=category.name,counterparty=supplier.name,lease_start_date=start,lease_end_date=end,classification="IFRS 16 Lessee",payment_frequency="Monthly",payment_timing="Arrears",discount_rate=12,currency="NGN",exchange_rate=1,rou_asset_account=accounts["1600"].name,lease_liability_account=accounts["2300"].name,interest_expense_account=accounts["5200"].name,accumulated_depreciation_account=accounts["1690"].name,depreciation_expense_account=accounts["5400"].name,payments=[{"due_date":due,"payment_amount":100},{"due_date":due+timedelta(days=30),"payment_amount":100},{"due_date":due+timedelta(days=60),"payment_amount":100},{"due_date":due+timedelta(days=90),"payment_amount":100},{"due_date":due+timedelta(days=120),"payment_amount":100},{"due_date":due+timedelta(days=150),"payment_amount":100},{"due_date":due+timedelta(days=180),"payment_amount":100},{"due_date":due+timedelta(days=210),"payment_amount":100},{"due_date":due+timedelta(days=240),"payment_amount":100},{"due_date":due+timedelta(days=270),"payment_amount":100},{"due_date":due+timedelta(days=300),"payment_amount":100},{"due_date":due+timedelta(days=330),"payment_amount":100}]).insert()
        lease=approve_submit(lease)
        assert lease.posting_batch and lease.right_of_use_asset
        schedule=lease.payments[0]
        with session_as(MAKER):
            payment=new_doc("Payment",payment_date=due,posting_date=due,purpose="Lease Payment",currency="NGN",exchange_rate=1,payment_method="Bank Transfer",cash_account=accounts["1000"].name,lease_reference=lease.name,lease_due_date=due,narration="Lease instalment",lines=[{"account":accounts["2300"].name,"amount":schedule.principal_reduction,"description":"Lease principal"},{"account":accounts["5200"].name,"amount":schedule.interest_expense,"description":"Lease interest"}]).insert()
        approve_submit(payment)
        refreshed=get_doc("Fixed Asset Lease",lease.name,ignore_permissions=True)
        paid=next(p for p in refreshed.payments if str(p.due_date)==str(due))
        assert paid.payment_status=="Paid" and paid.payment_reference==payment.name
    finally:
        velora.shutdown()

def test_purchase_invoice_capitalises_fixed_asset_without_duplicate_posting(tmp_path):
    accounts,supplier,category=setup_ops(tmp_path)
    try:
        today=date.today()
        with session_as(MAKER):
            invoice=new_doc("Purchase Invoice",invoice_date=today,posting_date=today,due_date=today+timedelta(days=30),party=supplier.name,currency="NGN",exchange_rate=1,narration="Capital equipment invoice",lines=[{"description":"Laptop workstation","quantity":2,"amount":2000,"account":accounts["1500"].name,"is_fixed_asset":1,"asset_category":category.name,"asset_name":"Laptop","useful_life_months":36,"residual_value":100}]).insert()
        invoice=approve_submit(invoice)
        assert invoice.posting_batch
        line=invoice.lines[0]
        created=line.created_assets.split(", ")
        assert len(created)==2
        first=get_doc("Fixed Asset",created[0],ignore_permissions=True)
        assert first.acquisition_cost==Decimal("1000.00")
        assert first.residual_value==Decimal("100.00")
        assert get_account_balance(accounts["1500"].name)==Decimal("2000.000000")
        assert get_account_balance(accounts["2100"].name)==Decimal("-2000.000000")
    finally:
        velora.shutdown()


def test_tax_depreciation_book_updates_subledger_without_gl_posting(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        today = date.today()
        with session_as(MAKER):
            asset = new_doc("Fixed Asset", asset_name="Tax Book Test Asset", asset_category=category.name,
                acquisition_date=today, acquisition_cost=1000, accumulated_depreciation=0,
                impairment_loss=0, revaluation_adjustment=0, residual_value=100, useful_life_months=12,
                asset_account=accounts["1500"].name, accumulated_depreciation_account=accounts["1590"].name,
                depreciation_method="Straight Line", depreciation_expense_account=accounts["5400"].name,
                depreciation_start_date=today, status="Active")
            asset.flags.trusted_source = True
            asset.insert(ignore_permissions=True)
            book = get_doc("Fixed Asset Depreciation Book", "TAX")   # seeded at install: every company database has its own Financial and Tax books
            balance = new_doc("Fixed Asset Book Balance", asset=asset.name,
                depreciation_book=book.name, acquisition_cost=900, residual_value=50,
                accumulated_depreciation=0, accumulated_impairment=0, depreciation_method="Straight Line",
                useful_life_months=12, depreciation_start_date=today).insert()
            run = new_doc("Fixed Asset Depreciation Run", depreciation_book=book.name,
                period_start=today, period_end=today + timedelta(days=30), posting_date=today + timedelta(days=30),
                approval_status="Pending", lines=[{"asset": asset.name}]).insert()
        run = approve_submit(run)
        updated = get_doc("Fixed Asset Book Balance", balance.name, ignore_permissions=True)
        assert updated.carrying_amount < Decimal("900.00")
        assert run.posting_batch is None
        financial_asset = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert financial_asset.carrying_amount == Decimal("1000.00")
    finally:
        velora.shutdown()


def test_component_purchase_and_component_depreciation_post_independently(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        today = date.today()
        with session_as(MAKER):
            invoice = new_doc("Purchase Invoice", invoice_date=today, posting_date=today,
                due_date=today + timedelta(days=30), party=supplier.name, currency="NGN", exchange_rate=1,
                narration="Componentised equipment acquisition",
                lines=[{"description":"Componentised machine", "quantity":1, "amount":1000,
                    "account":accounts["1500"].name, "is_fixed_asset":1, "asset_category":category.name,
                    "asset_name":"Machine", "useful_life_months":60, "residual_value":100}],
                asset_components=[
                    {"asset_line_name":"Machine", "component_code":"ENGINE", "component_name":"Engine",
                     "acquisition_cost":600, "residual_value":60, "useful_life_months":60,
                     "depreciation_method":"Straight Line", "depreciation_start_date":today},
                    {"asset_line_name":"Machine", "component_code":"BODY", "component_name":"Machine Body",
                     "acquisition_cost":400, "residual_value":40, "useful_life_months":120,
                     "depreciation_method":"Straight Line", "depreciation_start_date":today},
                ]).insert()
        invoice = approve_submit(invoice)
        asset_name = invoice.lines[0].created_assets
        asset = get_doc("Fixed Asset", asset_name, ignore_permissions=True)
        assert len(asset.components) == 2
        with session_as(MAKER):
            run = new_doc("Fixed Asset Depreciation Run", period_start=today,
                period_end=today + timedelta(days=30), posting_date=today + timedelta(days=30),
                approval_status="Pending", lines=[{"asset":asset.name}]).insert()
        run = approve_submit(run)
        refreshed = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert refreshed.carrying_amount < Decimal("1000.00")
        assert all(Decimal(str(c.accumulated_depreciation)) > 0 for c in refreshed.components)
        assert len(run.component_lines) == 2
    finally:
        velora.shutdown()


def test_lease_modification_remeasures_liability_and_versions_remaining_schedule(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        start = date.today(); end = start + timedelta(days=365)
        due_dates = [start + timedelta(days=30 * n) for n in range(1, 13)]
        with session_as(MAKER):
            lease = new_doc("Fixed Asset Lease", lease_type="Lease In (Lessee)",
                asset_name="Lease Remeasurement Asset", asset_category=category.name, counterparty=supplier.name,
                lease_start_date=start, lease_end_date=end, classification="IFRS 16 Lessee",
                payment_frequency="Monthly", payment_timing="Arrears", discount_rate=12, currency="NGN", exchange_rate=1,
                rou_asset_account=accounts["1600"].name, lease_liability_account=accounts["2300"].name,
                interest_expense_account=accounts["5200"].name, accumulated_depreciation_account=accounts["1690"].name,
                depreciation_expense_account=accounts["5400"].name,
                payments=[{"due_date":d,"payment_amount":100} for d in due_dates]).insert()
        lease = approve_submit(lease)
        first = lease.payments[0]
        with session_as(MAKER):
            payment = new_doc("Payment", payment_date=due_dates[0], posting_date=due_dates[0], purpose="Lease Payment",
                currency="NGN", exchange_rate=1, payment_method="Bank Transfer", cash_account=accounts["1000"].name,
                lease_reference=lease.name, lease_due_date=due_dates[0], narration="First lease instalment",
                lines=[{"account":accounts["2300"].name,"amount":first.principal_reduction,"description":"Lease principal"},
                       {"account":accounts["5200"].name,"amount":first.interest_expense,"description":"Lease interest"}]).insert()
        approve_submit(payment)
        remaining_dates = due_dates[1:]
        with session_as(MAKER):
            modification = new_doc("Fixed Asset Lease Modification", lease=lease.name,
                effective_date=due_dates[0], modification_reason="Change in Discount Rate",
                reason_details="Updated incremental borrowing rate following reassessment.", discount_rate=10,
                payments=[{"due_date":d,"payment_amount":100} for d in remaining_dates]).insert()
        modification = approve_submit(modification)
        refreshed = get_doc("Fixed Asset Lease", lease.name, ignore_permissions=True)
        assert modification.posting_batch
        assert refreshed.lease_liability_balance == modification.remeasured_liability
        assert any(p.payment_status == "Superseded" for p in refreshed.payments)
        assert sum(1 for p in refreshed.payments if p.payment_status == "Scheduled") == 11
    finally:
        velora.shutdown()


def test_cgu_impairment_posts_allocations_to_asset_ledger_lines(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        from velora_erp.finance.doctype._utils import db_update
        category_doc = get_doc("Fixed Asset Category", category.name, ignore_permissions=True)
        category_doc.impairment_account = accounts["1590"].name
        category_doc.impairment_expense_account = accounts["5400"].name
        category_doc.impairment_reversal_account = accounts["4000"].name
        category_doc.revaluation_surplus_account = accounts["3000"].name
        category_doc.save(ignore_permissions=True)
        assets = []
        today = date.today()
        with session_as(MAKER):
            for name in ("CGU Asset A", "CGU Asset B"):
                asset = new_doc("Fixed Asset", asset_name=name, asset_category=category.name,
                    acquisition_date=today, acquisition_cost=1000,
                    accumulated_depreciation=0, impairment_loss=0, revaluation_adjustment=100,
                    revaluation_surplus=100, revaluation_surplus_account=accounts["3000"].name,
                    residual_value=0, useful_life_months=60, asset_account=accounts["1500"].name,
                    accumulated_depreciation_account=accounts["1590"].name,
                    depreciation_method="Straight Line", depreciation_expense_account=accounts["5400"].name,
                    depreciation_start_date=today, impairment_account=accounts["1590"].name,
                    impairment_expense_account=accounts["5400"].name, status="Active")
                asset.flags.trusted_source = True
                asset.insert(ignore_permissions=True)
                assets.append(asset)
            cgu = new_doc("Fixed Asset CGU", cgu_name="Operations CGU",
                assets=[{"asset":assets[0].name,"individual_recoverable_floor":100},
                        {"asset":assets[1].name,"individual_recoverable_floor":100}]).insert()
            assessment = new_doc("Fixed Asset CGU Impairment", cgu=cgu.name,
                assessment_date=today, recoverable_amount=1800, valuation_reference="VAL-2026-001",
                approval_status="Pending").insert()
        assessment = approve_submit(assessment)
        assert assessment.posting_batch
        assert assessment.impairment_loss == Decimal("400.00")
        for asset in assets:
            refreshed = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
            assert refreshed.carrying_amount == Decimal("900.00")
            assert refreshed.impairment_loss == Decimal("200.00")
            assert refreshed.revaluation_surplus == Decimal("0.00")
            assert refreshed.impairment_against_revaluation_surplus == Decimal("100.00")
            assert refreshed.impairment_charged_to_expense == Decimal("100.00")
        assert len(assessment.lines) == 2
        assert sum((line.revaluation_surplus_release for line in assessment.lines),Decimal("0")) == Decimal("200.00")
        assert sum((line.impairment_expense_amount for line in assessment.lines),Decimal("0")) == Decimal("200.00")
        assert get_account_balance(accounts["3000"].name) == Decimal("200.000000")
        assert get_account_balance(accounts["5400"].name) == Decimal("200.000000")
    finally:
        velora.shutdown()


def test_impairment_and_reversal_respect_revaluation_surplus_accounting(tmp_path):
    accounts, supplier, category = setup_ops(tmp_path)
    try:
        category_doc = get_doc("Fixed Asset Category", category.name, ignore_permissions=True)
        category_doc.impairment_account = accounts["1590"].name
        category_doc.impairment_expense_account = accounts["5400"].name
        category_doc.impairment_reversal_account = accounts["4000"].name
        category_doc.revaluation_surplus_account = accounts["3000"].name
        category_doc.save(ignore_permissions=True)
        today = date.today()
        with session_as(MAKER):
            asset = new_doc("Fixed Asset", asset_name="Revalued Impairment Asset", asset_category=category.name,
                acquisition_date=today, acquisition_cost=1000, accumulated_depreciation=0,
                impairment_loss=0, impairment_against_revaluation_surplus=0, impairment_charged_to_expense=0,
                revaluation_adjustment=100, revaluation_surplus=100, revaluation_surplus_account=accounts["3000"].name,
                residual_value=0, useful_life_months=60, asset_account=accounts["1500"].name,
                accumulated_depreciation_account=accounts["1590"].name, depreciation_method="Straight Line",
                depreciation_expense_account=accounts["5400"].name, depreciation_start_date=today,
                impairment_account=accounts["1590"].name, impairment_expense_account=accounts["5400"].name,
                impairment_reversal_account=accounts["4000"].name, status="Active")
            asset.flags.trusted_source = True
            asset.insert(ignore_permissions=True)
            assert get_doc("Fixed Asset", asset.name, ignore_permissions=True).revaluation_surplus == Decimal("100.00")
            impairment = new_doc("Fixed Asset Impairment", asset=asset.name,
                assessment_date=today, action="Recognise Impairment", recoverable_amount=950,
                valuation_reference="IAS36-VAL-001", approval_status="Pending").insert()
        impairment = approve_submit(impairment)
        impaired = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert impaired.revaluation_surplus == Decimal("0.00")
        assert impaired.impairment_against_revaluation_surplus == Decimal("100.00")
        assert impaired.impairment_charged_to_expense == Decimal("50.00")
        assert impairment.revaluation_surplus_movement == Decimal("100.00")
        assert impairment.profit_or_loss_movement == Decimal("50.00")
        with session_as(MAKER):
            reversal = new_doc("Fixed Asset Impairment", asset=asset.name,
                assessment_date=today, action="Reverse Impairment", recoverable_amount=1050,
                valuation_reference="IAS36-REV-001", approval_status="Pending").insert()
        reversal = approve_submit(reversal)
        restored = get_doc("Fixed Asset", asset.name, ignore_permissions=True)
        assert restored.carrying_amount == Decimal("1050.00")
        assert restored.impairment_loss == Decimal("50.00")
        assert restored.revaluation_surplus == Decimal("50.00")
        assert restored.impairment_against_revaluation_surplus == Decimal("50.00")
        assert restored.impairment_charged_to_expense == Decimal("0.00")
        assert reversal.revaluation_surplus_movement == Decimal("50.00")
        assert reversal.profit_or_loss_movement == Decimal("50.00")
        assert get_account_balance(accounts["3000"].name) == Decimal("50.000000")
        assert get_account_balance(accounts["5400"].name) == Decimal("50.000000")
        assert get_account_balance(accounts["4000"].name) == Decimal("-50.000000")
    finally:
        velora.shutdown()
