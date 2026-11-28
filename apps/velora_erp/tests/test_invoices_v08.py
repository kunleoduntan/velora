from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc
from velora.permissions import Session, session_as
from velora_erp.finance.engine import get_account_balance
from velora_erp.setup import after_install

MAKER=Session('invoice-maker@example.test',frozenset({'Accountant'}))
APPROVER=Session('invoice-approver@example.test',frozenset({'Finance Manager'}))

def setup(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'invoice.db'}",apps=['velora_erp', 'velora_projectone'],developer_mode=True); velora.init(); velora.migrate(); after_install()
    from item_seed import seed_items; seed_items('ITEM-001','ITEM-002','ITEM-LC-1','SERVICE-01','SERVICE-RET','ITEM-01','ITEM-02','ITEM-03')
    today=date.today(); y=today.year
    new_doc('Financial Year',year_name=f'FY-{y}',start_date=date(y,1,1),end_date=date(y,12,31),status='Open',is_current=1).insert(ignore_permissions=True)
    new_doc('Financial Period',period_name=f'FY-{y}-P01',financial_year=f'FY-{y}',period_number=1,start_date=date(y,1,1),end_date=date(y,12,31),status='Open').insert(ignore_permissions=True)
    groups={}
    for c,n,r in [('A','Assets','Asset'),('L','Liabilities','Liability'),('I','Income','Income'),('X','Expense','Expense')]: groups[c]=new_doc('Account Group',group_code=c,group_name=n,root_type=r,is_group=0).insert(ignore_permissions=True)
    def acc(code,name,g,typ,**kw): return new_doc('Account',account_code=code,account_name=name,account_group=g,account_type=typ,allow_manual_posting=1,**kw).insert(ignore_permissions=True)
    ar=acc('1100','Receivables','A','RECEIVABLE',is_control_account=1,control_account_type='Receivables',requires_party=1)
    ap=acc('2100','Payables','L','PAYABLE',is_control_account=1,control_account_type='Payables',requires_party=1)
    rev=acc('4000','Sales Revenue','I','REVENUE'); exp=acc('5000','Purchases','X','OPERATING_EXPENSE')
    vatout=acc('2200','Output VAT','L','TAX_PAYABLE'); vatin=acc('1200','Input VAT','A','CLEARING')
    new_doc('Customer Group',group_code='CG',group_name='Customers',is_group=0).insert(ignore_permissions=True)
    new_doc('Supplier Group',group_code='SG',group_name='Suppliers',is_group=0).insert(ignore_permissions=True)
    cust=new_doc('Customer',customer_code='C001',customer_name='Customer One',customer_group='CG',customer_type='Company',control_account=ar.name).insert(ignore_permissions=True)
    supp=new_doc('Supplier',supplier_code='S001',supplier_name='Supplier One',supplier_group='SG',supplier_type='Company',control_account=ap.name).insert(ignore_permissions=True)
    return {'ar':ar,'ap':ap,'rev':rev,'exp':exp,'vatout':vatout,'vatin':vatin,'cust':cust,'supp':supp}

def approve_submit(doc):
    with session_as(APPROVER):
        doc=get_doc(doc.doctype,doc.name); doc.approval_status='Approved'; doc.save(ignore_permissions=True); doc.submit(ignore_permissions=True); doc.reload()
    return doc

def test_sales_invoice_posts_gross_receivable_and_revenue_tax(tmp_path):
    a=setup(tmp_path)
    try:
        with session_as(MAKER):
            doc=new_doc('Sales Invoice',invoice_date=date.today(),posting_date=date.today(),due_date=date.today(),party=a['cust'].name,currency='NGN',exchange_rate=1,narration='Consulting service',lines=[{'account':a['rev'].name,'description':'Consulting','amount':1000,'tax_account':a['vatout'].name,'tax_rate':7.5,'tax_amount':75}]).insert()
        approve_submit(doc)
        assert get_account_balance(a['ar'].name)==Decimal('1075.000000')
        assert get_account_balance(a['rev'].name)==Decimal('-1000.000000')
        assert get_account_balance(a['vatout'].name)==Decimal('-75.000000')
    finally: velora.shutdown()

def test_purchase_invoice_posts_expense_input_tax_and_payable(tmp_path):
    a=setup(tmp_path)
    try:
        with session_as(MAKER):
            doc=new_doc('Purchase Invoice',invoice_date=date.today(),posting_date=date.today(),due_date=date.today(),party=a['supp'].name,currency='NGN',exchange_rate=1,narration='Office supplies',lines=[{'account':a['exp'].name,'description':'Supplies','amount':2000,'tax_account':a['vatin'].name,'tax_rate':7.5,'tax_amount':150}]).insert()
        approve_submit(doc)
        assert get_account_balance(a['exp'].name)==Decimal('2000.000000')
        assert get_account_balance(a['vatin'].name)==Decimal('150.000000')
        assert get_account_balance(a['ap'].name)==Decimal('-2150.000000')
    finally: velora.shutdown()

def test_sales_return_created_from_invoice_reverses_revenue_tax_and_receivable(tmp_path):
    from velora_erp.finance.document_flow.conversion import create_document_from
    a=setup(tmp_path)
    try:
        with session_as(MAKER):
            invoice=new_doc('Sales Invoice',invoice_date=date.today(),posting_date=date.today(),due_date=date.today(),party=a['cust'].name,currency='NGN',exchange_rate=1,narration='Goods sold',lines=[{'account':a['rev'].name,'description':'Goods','amount':1000,'tax_account':a['vatout'].name,'tax_rate':7.5,'tax_amount':75,'item_code':'ITEM-01','quantity':10,'uom':'Each'}]).insert()
        invoice=approve_submit(invoice)
        with session_as(MAKER):
            ret=create_document_from('Sales Invoice',invoice.name,'Sales Return',{})
            assert ret.source_invoice==invoice.name
            assert ret.lines[0].source_line==invoice.lines[0].name
            assert ret.lines[0].amount==1000
        ret=approve_submit(ret)
        assert get_account_balance(a['ar'].name)==Decimal('0.000000')
        assert get_account_balance(a['rev'].name)==Decimal('0.000000')
        assert get_account_balance(a['vatout'].name)==Decimal('0.000000')
    finally: velora.shutdown()


def test_purchase_return_created_from_invoice_reverses_expense_tax_and_payable(tmp_path):
    from velora_erp.finance.document_flow.conversion import create_document_from
    a=setup(tmp_path)
    try:
        with session_as(MAKER):
            invoice=new_doc('Purchase Invoice',invoice_date=date.today(),posting_date=date.today(),due_date=date.today(),party=a['supp'].name,currency='NGN',exchange_rate=1,narration='Goods bought',lines=[{'account':a['exp'].name,'description':'Goods','amount':2000,'tax_account':a['vatin'].name,'tax_rate':7.5,'tax_amount':150,'item_code':'ITEM-02','quantity':5,'uom':'Each'}]).insert()
        invoice=approve_submit(invoice)
        with session_as(MAKER):
            ret=create_document_from('Purchase Invoice',invoice.name,'Purchase Return',{})
            assert ret.source_invoice==invoice.name
            assert ret.lines[0].amount==2000
        ret=approve_submit(ret)
        assert get_account_balance(a['ap'].name)==Decimal('0.000000')
        assert get_account_balance(a['exp'].name)==Decimal('0.000000')
        assert get_account_balance(a['vatin'].name)==Decimal('0.000000')
    finally: velora.shutdown()

def test_partial_sales_returns_are_capped_by_invoice_quantity_and_value(tmp_path):
    from velora_erp.finance.document_flow.conversion import create_document_from
    from velora.exceptions import ValidationError
    a=setup(tmp_path)
    try:
        with session_as(MAKER):
            invoice=new_doc('Sales Invoice',invoice_date=date.today(),posting_date=date.today(),due_date=date.today(),party=a['cust'].name,currency='NGN',exchange_rate=1,narration='Part delivery sale',lines=[{'account':a['rev'].name,'description':'Product','amount':1000,'tax_account':a['vatout'].name,'tax_amount':75,'item_code':'ITEM-03','quantity':10,'uom':'Each'}]).insert()
        invoice=approve_submit(invoice)
        key=invoice.lines[0].name
        with session_as(MAKER):
            first=create_document_from('Sales Invoice',invoice.name,'Sales Return',{'quantities':{key:4}})
            assert first.lines[0].quantity==4
            assert first.lines[0].amount==400
            assert first.lines[0].tax_amount==30
            second=create_document_from('Sales Invoice',invoice.name,'Sales Return',{})
            assert second.lines[0].quantity==6
            assert second.lines[0].amount==600
            assert second.lines[0].tax_amount==45
            with pytest.raises(ValidationError,match='fully returned'):
                create_document_from('Sales Invoice',invoice.name,'Sales Return',{})
    finally: velora.shutdown()
