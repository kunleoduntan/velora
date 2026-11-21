from datetime import date
import velora
import pytest
from velora import new_doc, get_doc
from velora.exceptions import ValidationError
from velora.permissions import Session, session_as
from velora_erp.setup import after_install
from velora_erp.finance.document_flow.conversion import create_document_from

MAKER = Session('flow-maker@example.test', frozenset({'Accountant'}))
APPROVER = Session('flow-approver@example.test', frozenset({'Finance Manager'}))


def setup_flow(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'flow.db'}", apps=['velora_erp'], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    from item_seed import seed_items; seed_items('ITEM-001','ITEM-002','ITEM-LC-1','SERVICE-01','SERVICE-RET','ITEM-01','ITEM-02','ITEM-03')
    today=date.today(); year=today.year
    new_doc('Financial Year',year_name=f'FY-{year}',start_date=date(year,1,1),end_date=date(year,12,31),status='Open',is_current=1).insert(ignore_permissions=True)
    new_doc('Financial Period',period_name=f'FY-{year}-P01',financial_year=f'FY-{year}',period_number=1,start_date=date(year,1,1),end_date=date(year,12,31),status='Open').insert(ignore_permissions=True)
    groups = {}
    for code, label, root in [('A','Assets','Asset'),('L','Liabilities','Liability'),('I','Income','Income'),('X','Expense','Expense')]:
        groups[code] = new_doc('Account Group', group_code=code, group_name=label, root_type=root, is_group=0).insert(ignore_permissions=True)
    def account(code, label, group, typ, **extra):
        return new_doc('Account', account_code=code, account_name=label, account_group=groups[group].name, account_type=typ, allow_manual_posting=1, **extra).insert(ignore_permissions=True)
    bank=account('1000','Main Bank','A','BANK')
    ar=account('1100','Receivables','A','RECEIVABLE',is_control_account=1,control_account_type='Receivables',requires_party=1)
    ap=account('2100','Payables','L','PAYABLE',is_control_account=1,control_account_type='Payables',requires_party=1)
    revenue=account('4000','Revenue','I','REVENUE')
    expense=account('5000','Expense','X','OPERATING_EXPENSE')
    new_doc('Customer Group',group_code='CG',group_name='Customers',is_group=0).insert(ignore_permissions=True)
    new_doc('Supplier Group',group_code='SG',group_name='Suppliers',is_group=0).insert(ignore_permissions=True)
    new_doc('Warehouse',name='Main Store',warehouse_name='Main Store',is_group=0).insert(ignore_permissions=True)
    customer=new_doc('Customer',customer_code='C001',customer_name='Customer',customer_group='CG',customer_type='Company',control_account=ar.name).insert(ignore_permissions=True)
    supplier=new_doc('Supplier',supplier_code='S001',supplier_name='Supplier',supplier_group='SG',supplier_type='Company',control_account=ap.name).insert(ignore_permissions=True)
    return bank, customer, supplier, revenue, expense, ar, ap


def test_sales_invoice_create_receipt_preserves_source_and_gross_amount(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            invoice = new_doc('Sales Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1, narration='Services', lines=[{'account':revenue.name,'description':'Consulting','amount':1000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            invoice=get_doc('Sales Invoice',invoice.name); invoice.approval_status='Approved'; invoice.save(ignore_permissions=True); invoice.submit(ignore_permissions=True)
        with session_as(MAKER):
            receipt = create_document_from('Sales Invoice', invoice.name, 'Receipt', {'cash_account':bank.name, 'settlement_amount':400})
        assert receipt.docstatus == 0
        assert receipt.source_doctype == 'Sales Invoice'
        assert receipt.source_document == invoice.name
        assert receipt.purpose == 'Customer Receipt'
        assert receipt.lines[0].party == customer.name
        assert receipt.lines[0].account == ar.name
        assert receipt.lines[0].amount == 400
        assert receipt.lines[0].allocation_amount == 400
        assert receipt.lines[0].entry_side == 'Credit'
        # part-payments are allowed, capped at what is still outstanding after draft receipts
        rest = create_document_from('Sales Invoice', invoice.name, 'Receipt', {'cash_account':bank.name})
        assert rest.lines[0].amount == 600
        with pytest.raises(ValidationError):
            create_document_from('Sales Invoice', invoice.name, 'Receipt', {'cash_account':bank.name})
    finally:
        velora.shutdown()


def test_purchase_invoice_create_payment_maps_supplier_and_gross_amount(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            invoice = new_doc('Purchase Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=supplier.name, currency='NGN', exchange_rate=1, narration='Services', lines=[{'account':expense.name,'description':'Consulting','amount':2000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            invoice=get_doc('Purchase Invoice',invoice.name); invoice.approval_status='Approved'; invoice.save(ignore_permissions=True); invoice.submit(ignore_permissions=True)
        with session_as(MAKER):
            payment = create_document_from('Purchase Invoice', invoice.name, 'Payment', {'cash_account':bank.name})
        assert payment.docstatus == 0
        assert payment.source_doctype == 'Purchase Invoice'
        assert payment.source_document == invoice.name
        assert payment.purpose == 'Supplier Payment'
        assert payment.lines[0].party == supplier.name
        assert payment.lines[0].amount == 2000
        assert payment.lines[0].account == ap.name
        assert payment.lines[0].entry_side == 'Debit'
    finally:
        velora.shutdown()


def test_create_from_rejects_unsubmitted_source(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            invoice = new_doc('Sales Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1, narration='Services', lines=[{'account':revenue.name,'description':'Consulting','amount':1000}]).insert(ignore_permissions=True)
            with pytest.raises(ValidationError):
                create_document_from('Sales Invoice', invoice.name, 'Receipt', {'cash_account':bank.name})
    finally:
        velora.shutdown()


def test_create_from_action_registry_only_exposes_implemented_flows(tmp_path):
    from velora_erp.finance.document_flow.api import get_document_flow_catalogue
    from velora_erp.finance.document_flow.registry import get_document_flows
    rows = get_document_flows('Sales Invoice')
    assert [r['target_doctype'] for r in rows] == ['Receipt', 'Sales Return']
    assert rows[0]['available'] is True
    catalogue = get_document_flow_catalogue('Sales Invoice')
    assert {r['target_doctype'] for r in catalogue} >= {'Receipt', 'Sales Return', 'Delivery Note', 'Waybill'}
    assert all(r['available'] is False for r in catalogue if r['status'] == 'planned')


def test_create_from_registry_rejects_planned_target(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            invoice = new_doc('Sales Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1, narration='Services', lines=[{'account':revenue.name,'description':'Consulting','amount':1000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            invoice=get_doc('Sales Invoice',invoice.name); invoice.approval_status='Approved'; invoice.save(ignore_permissions=True); invoice.submit(ignore_permissions=True)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match='not implemented or enabled'):
                create_document_from('Sales Invoice', invoice.name, 'Delivery Note', {})
    finally:
        velora.shutdown()


def test_sales_order_partial_delivery_and_waybill_preserve_lineage(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            order = new_doc('Sales Order', document_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1,
                lines=[{'item_code':'ITEM-001','description':'Office chair','quantity':10,'uom':'Each','rate':25000}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order=get_doc('Sales Order', order.name)
            source_line=order.lines[0].name
            first = create_document_from('Sales Order', order.name, 'Delivery Note', {'quantities':{source_line:4}, 'delivery_address':'Lagos'})
            assert first.lines[0].quantity == 4
            assert first.lines[0].source_line == source_line
            assert first.source_doctype == 'Sales Order'
            assert first.source_document == order.name
            second = create_document_from('Sales Order', order.name, 'Delivery Note', {'quantities':{source_line:6}})
            assert second.lines[0].quantity == 6
            with pytest.raises(ValidationError, match='remaining quantity'):
                create_document_from('Sales Order', order.name, 'Delivery Note', {'quantities':{source_line:1}})
            first.submit(ignore_permissions=True)
            # A submitted delivery note can generate one transport document.
            first = get_doc('Delivery Note', first.name)
            waybill = create_document_from('Delivery Note', first.name, 'Waybill', {'transporter':'Velora Logistics','vehicle_number':'ABC-123'})
            with pytest.raises(ValidationError, match='already been created'):
                create_document_from('Delivery Note', first.name, 'Waybill', {})
            assert waybill.delivery_note == first.name
            assert waybill.party == customer.name
            assert waybill.lines[0].quantity == 4
            assert waybill.source_doctype == 'Delivery Note'
    finally:
        velora.shutdown()


def test_purchase_order_partial_receipts_enforce_ordered_quantity(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            order = new_doc('Purchase Order', document_date=date.today(), party=supplier.name, currency='NGN', exchange_rate=1,
                lines=[{'item_code':'ITEM-002','description':'Printer paper','quantity':50,'uom':'Ream','rate':8000}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order=get_doc('Purchase Order', order.name)
            source_line=order.lines[0].name
            first=create_document_from('Purchase Order',order.name,'Purchase Receipt',{'quantities':{source_line:20},'warehouse':'Main Store'})
            second=create_document_from('Purchase Order',order.name,'Purchase Receipt',{'quantities':{source_line:30}})
            assert first.lines[0].quantity == 20
            assert second.lines[0].quantity == 30
            with pytest.raises(ValidationError, match='remaining quantity'):
                create_document_from('Purchase Order',order.name,'Purchase Receipt',{'quantities':{source_line:1}})
    finally:
        velora.shutdown()


def test_operational_document_flow_registry_exposes_only_implemented_transitions():
    from velora_erp.finance.document_flow.registry import get_document_flows
    assert [x['target_doctype'] for x in get_document_flows('Sales Order')] == ['Delivery Note', 'Sales Invoice', 'Receipt']
    assert [x['target_doctype'] for x in get_document_flows('Purchase Order')] == ['Purchase Receipt', 'Purchase Invoice', 'Payment']
    assert [x['target_doctype'] for x in get_document_flows('Delivery Note')] == ['Sales Invoice', 'Waybill', 'Quality Inspection']


def test_framework_document_flow_rest_api_lists_actions_and_creates_target(tmp_path):
    from fastapi.testclient import TestClient
    from velora.api.app import create_app
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            order = new_doc('Sales Order', document_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1,
                lines=[{'description':'Desk','quantity':3,'uom':'Each','rate':100}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
        client=TestClient(create_app(auto_init=False))
        headers={'X-Velora-User':MAKER.user,'X-Velora-Roles':'Accountant'}
        actions=client.get(f'/api/document-flow/Sales%20Order/{order.name}/actions',headers=headers)
        assert actions.status_code == 200, actions.text
        assert actions.json()['data'][0]['target_doctype'] == 'Delivery Note'
        created=client.post(f'/api/document-flow/Sales%20Order/{order.name}/create',headers=headers,json={'target_doctype':'Delivery Note','overrides':{'quantities':{order.lines[0].name:2}}})
        assert created.status_code == 200, created.text
        assert created.json()['data']['source_document'] == order.name
        assert created.json()['data']['doctype'] == 'Delivery Note'
    finally:
        velora.shutdown()


def test_sales_and_purchasing_have_separate_native_workspaces(tmp_path):
    from velora.application_workspaces import listing
    setup_flow(tmp_path)
    try:
        rows=listing()
        names={row['name']:row for row in rows if row.get('scope')=='company'}
        assert {'Sales','Purchasing','Finance'} <= set(names)
        sales={w['title'] for w in names['Sales']['layout']}
        purchasing={w['title'] for w in names['Purchasing']['layout']}
        assert {'Sales Orders','Delivery Notes','Waybills','Sales Invoices'} <= sales
        assert {'Purchase Orders','Purchase Receipts','Purchase Invoices'} <= purchasing
    finally:
        velora.shutdown()


def test_landed_cost_voucher_allocates_and_requires_independent_approval_before_capitalisation(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            order=new_doc('Purchase Order',document_date=date.today(),party=supplier.name,currency='NGN',exchange_rate=1,
                lines=[{'item_code':'ITEM-LC-1','description':'Imported spare part','quantity':2,'uom':'Each','rate':500}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order=get_doc('Purchase Order',order.name)
            receipt=create_document_from('Purchase Order',order.name,'Purchase Receipt',{'warehouse':'Main Store'})
            receipt.submit(ignore_permissions=True)
            receipt=get_doc('Purchase Receipt',receipt.name)
            voucher=new_doc('Landed Cost Voucher',voucher_date=date.today(),purchase_receipt=receipt.name,currency='NGN',exchange_rate=1,
                allocation_method='By Value',narration='Freight and port handling',
                charges=[{'description':'Freight','charge_account':expense.name,'amount':100}],
                allocations=[{'item_code':'ITEM-LC-1','source_line':receipt.lines[0].name,'quantity':2,'item_value':1000}]).insert(ignore_permissions=True)
            assert voucher.total_charges==100
            assert voucher.allocated_total==100
            assert voucher.allocations[0].allocated_amount==100
            assert voucher.allocation_status=='Balanced'
            assert voucher.meta.is_submittable is True
            assert voucher.approval_status == 'Approved'        # no approval workflow in this company
        from wf_helpers import install_approval
        install_approval('Landed Cost Voucher')
        with session_as(MAKER):
            held=new_doc('Landed Cost Voucher',voucher_date=date.today(),purchase_receipt=receipt.name,currency='NGN',exchange_rate=1,
                allocation_method='By Value',narration='Held for approval',
                charges=[{'description':'Freight','charge_account':expense.name,'amount':100}],
                allocations=[{'item_code':'ITEM-LC-1','source_line':receipt.lines[0].name,'quantity':2,'item_value':1000}]).insert(ignore_permissions=True)
            assert held.approval_status == 'Pending'
            with pytest.raises(ValidationError, match='approval workflow'):
                held.submit(ignore_permissions=True)
    finally:
        velora.shutdown()
