from datetime import date
from decimal import Decimal
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora.permissions import session_as
from test_document_flow import setup_flow, MAKER, APPROVER
from velora_erp.finance.inventory.ledger import calculate_reconciliation_values, get_stock_balance
from velora_erp.finance.document_flow.conversion import create_document_from


def setup_inventory(tmp_path):
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    asset_group = new_doc('Account Group', group_code='INVASSET', group_name='Inventory Assets', root_type='Asset', is_group=0).insert(ignore_permissions=True)
    liability_group = new_doc('Account Group', group_code='INVLIAB', group_name='Inventory Liabilities', root_type='Liability', is_group=0).insert(ignore_permissions=True)
    income_group = new_doc('Account Group', group_code='INVINC', group_name='Inventory Income', root_type='Income', is_group=0).insert(ignore_permissions=True)
    def account(code, label, group, typ):
        return new_doc('Account', account_code=code, account_name=label, account_group=group.name, account_type=typ, allow_manual_posting=1).insert(ignore_permissions=True)
    inventory = account('1300','Inventory Asset',asset_group,'INVENTORY')
    grni = account('2200','Goods Received Not Invoiced',liability_group,'ACCRUAL')
    cogs = account('5100','Cost of Goods Sold',new_doc('Account Group',group_code='COGS',group_name='COGS',root_type='Expense',is_group=0).insert(ignore_permissions=True),'COST_OF_SALES')
    gain = account('4100','Stock Adjustment Gain',income_group,'OTHER_INCOME')
    loss = account('5200','Stock Adjustment Loss',new_doc('Account Group',group_code='STLOSS',group_name='Stock Loss',root_type='Expense',is_group=0).insert(ignore_permissions=True),'OPERATING_EXPENSE')
    ppv = account('5300','Purchase Price Variance',new_doc('Account Group',group_code='PPV',group_name='Purchase Price Variance',root_type='Expense',is_group=0).insert(ignore_permissions=True),'OPERATING_EXPENSE')
    new_doc('Inventory Settings', settings_name='Primary Inventory Settings', default_inventory_asset_account=inventory.name,
        goods_received_not_invoiced_account=grni.name, cost_of_goods_sold_account=cogs.name,
        stock_adjustment_gain_account=gain.name, stock_adjustment_loss_account=loss.name, purchase_price_variance_account=ppv.name).insert(ignore_permissions=True)
    item = new_doc('Inventory Item', name='ITEM-STOCK-1', item_name='Test Stock Item', stock_uom='Each', tracking_mode='None', standard_rate=100).insert(ignore_permissions=True)
    warehouse = get_doc('Warehouse','Main Store')
    return item, warehouse, inventory, grni, cogs, gain, loss


def approve_and_submit(doc):
    with session_as(APPROVER):
        doc = get_doc(doc.doctype, doc.name)
        doc.approval_status = 'Approved'
        doc.save(ignore_permissions=True)
        doc.submit(ignore_permissions=True)
    return get_doc(doc.doctype, doc.name)


def test_stock_reconciliation_calculates_quantity_and_valuation_adjustments():
    result = calculate_reconciliation_values(Decimal('10'), Decimal('1000'), Decimal('8'), Decimal('120'))
    assert result['adjustment_qty'] == Decimal('-2.000000')
    assert result['adjustment_value'] == Decimal('-200.00')
    assert result['new_stock_value'] == Decimal('800.00')
    assert result['new_valuation_rate'] == Decimal('100')
    unchanged = calculate_reconciliation_values(8, 800, 8, 125)
    assert unchanged['adjustment_qty'] == Decimal('0.000000')
    assert unchanged['adjustment_value'] == Decimal('0.00')
    increase = calculate_reconciliation_values(10, 1000, 15, 120)
    assert increase['adjustment_qty'] == Decimal('5.000000')
    assert increase['adjustment_value'] == Decimal('600.00')
    assert increase['new_stock_value'] == Decimal('1600.00')
    zero = calculate_reconciliation_values(8, 1000, 0, 0)
    assert zero['adjustment_qty'] == Decimal('-8.000000')
    assert zero['adjustment_value'] == Decimal('-1000.00')


def test_stock_reconciliation_posts_immutable_ledger_and_financial_adjustment(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        with session_as(MAKER):
            recon = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                remarks='Initial physical count', items=[{'item_code':item.name,'physical_qty':10,'proposed_rate':100}]).insert(ignore_permissions=True)
        recon = approve_and_submit(recon)
        balance = get_stock_balance(item.name, warehouse.name)
        assert balance['qty'] == Decimal('10.000000')
        assert balance['value'] == Decimal('1000.00')
        assert recon.inventory_posting_batch
        ledger_rows = __import__('velora').get_list('Stock Ledger Record', filters={'voucher_no':recon.name}, fields=['name'])
        assert len(ledger_rows) == 1
        ledger_record = get_doc('Stock Ledger Record', ledger_rows[0]['name'])
        with pytest.raises(ValidationError, match='immutable'):
            ledger_record.save(ignore_permissions=True)
        with pytest.raises(ValidationError, match='cannot be deleted'):
            ledger_record.delete(ignore_permissions=True)
        with session_as(MAKER):
            with pytest.raises(ValidationError, match='Backdated stock posting'):
                new_doc('Stock Reconciliation', posting_date=date(2000,1,1), warehouse=warehouse.name,
                    items=[{'item_code':item.name,'physical_qty':9,'proposed_rate':100}]).insert(ignore_permissions=True)
        with session_as(MAKER):
            second = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                remarks='Count correction', items=[{'item_code':item.name,'physical_qty':8,'proposed_rate':120}]).insert(ignore_permissions=True)
        second = approve_and_submit(second)
        balance = get_stock_balance(item.name, warehouse.name)
        assert balance['qty'] == Decimal('8.000000')
        assert balance['value'] == Decimal('800.00')
        assert second.inventory_posting_batch
    finally:
        velora.shutdown()


def test_serial_and_batch_tracking_are_required_by_item_configuration(tmp_path):
    item, warehouse, *_ = setup_inventory(tmp_path)
    try:
        batch_item = new_doc('Inventory Item', name='ITEM-BATCH-1', item_name='Batch Item', stock_uom='Each', tracking_mode='Batch', standard_rate=50).insert(ignore_permissions=True)
        batch = new_doc('Batch', name='BATCH-001', batch_number='BATCH-001', item_code=batch_item.name).insert(ignore_permissions=True)
        with session_as(MAKER):
            recon = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                items=[{'item_code':batch_item.name,'physical_qty':5,'proposed_rate':50,'batch':batch.name}]).insert(ignore_permissions=True)
            assert recon.items[0].adjustment_qty == 5
            with pytest.raises(ValidationError, match='Batch'):
                new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                    items=[{'item_code':batch_item.name,'physical_qty':5,'proposed_rate':50}]).insert(ignore_permissions=True)
        serial_item = new_doc('Inventory Item', name='ITEM-SERIAL-1', item_name='Serial Item', stock_uom='Each', tracking_mode='Serial Number', standard_rate=75).insert(ignore_permissions=True)
        serial = new_doc('Serial Number', name='SN-001', serial_number='SN-001', item_code=serial_item.name).insert(ignore_permissions=True)
        with session_as(MAKER):
            serial_recon = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                items=[{'item_code':serial_item.name,'physical_qty':1,'proposed_rate':75,'serial_number':serial.name}]).insert(ignore_permissions=True)
            assert serial_recon.items[0].adjustment_qty == 1
    finally:
        velora.shutdown()


def test_purchase_receipt_and_landed_cost_update_stock_valuation_and_accounting(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        with session_as(MAKER):
            order = new_doc('Purchase Order', document_date=date.today(), party='S001', currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'Test Stock Item','quantity':2,'uom':'Each','rate':500}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = get_doc('Purchase Order', order.name)
            receipt = __import__('velora_erp.finance.document_flow.conversion', fromlist=['create_document_from']).create_document_from(
                'Purchase Order', order.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt.submit(ignore_permissions=True)
            receipt = get_doc('Purchase Receipt', receipt.name)
            balance = get_stock_balance(item.name, warehouse.name)
            assert balance['qty'] == Decimal('2.000000')
            assert balance['value'] == Decimal('1000.00')
            # Consume one of the two received units before the freight invoice is capitalised.
            customer_name = __import__('velora').get_list('Customer', fields=['name'], limit=1)[0]['name']
            sales_order = new_doc('Sales Order', document_date=date.today(), party=customer_name, currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'Test Stock Item','quantity':1,'uom':'Each','rate':700}]).insert(ignore_permissions=True)
            sales_order.submit(ignore_permissions=True)
            sales_order = get_doc('Sales Order', sales_order.name)
            delivery = __import__('velora_erp.finance.document_flow.conversion', fromlist=['create_document_from']).create_document_from(
                'Sales Order', sales_order.name, 'Delivery Note', {'warehouse':warehouse.name})
            delivery.submit(ignore_permissions=True)
            balance = get_stock_balance(item.name, warehouse.name)
            assert balance['qty'] == Decimal('1.000000')
            assert balance['value'] == Decimal('500.00')
            voucher = new_doc('Landed Cost Voucher', voucher_date=date.today(), purchase_receipt=receipt.name,
                currency='NGN', exchange_rate=1, allocation_method='By Value', narration='Freight capitalisation',
                charges=[{'description':'Freight','charge_account':'5000','amount':100}],
                allocations=[{'item_code':item.name,'source_line':receipt.lines[0].name,'quantity':2,'item_value':1000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            voucher = get_doc('Landed Cost Voucher', voucher.name)
            voucher.approval_status = 'Approved'; voucher.save(ignore_permissions=True); voucher.submit(ignore_permissions=True)
        balance = get_stock_balance(item.name, warehouse.name)
        assert balance['qty'] == Decimal('1.000000')
        assert balance['value'] == Decimal('550.00')
        assert balance['rate'] == Decimal('550')
        voucher = get_doc('Landed Cost Voucher', voucher.name)
        assert voucher.posting_batch
    finally:
        velora.shutdown()


def test_delivery_and_sales_purchase_returns_post_inventory_movements(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        # Establish 10 units through an approved stock reconciliation.
        with session_as(MAKER):
            recon = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                items=[{'item_code':item.name,'physical_qty':10,'proposed_rate':100}]).insert(ignore_permissions=True)
        approve_and_submit(recon)
        customer = __import__('velora').get_list('Customer', fields=['name'], limit=1)[0]['name']
        supplier = __import__('velora').get_list('Supplier', fields=['name'], limit=1)[0]['name']
        revenue = __import__('velora').get_list('Account', filters={'account_code':'4000'}, fields=['name'], limit=1)[0]['name']
        expense = __import__('velora').get_list('Account', filters={'account_code':'5000'}, fields=['name'], limit=1)[0]['name']
        from velora_erp.finance.document_flow.conversion import create_document_from

        # Delivery Note issues two units at the current moving-average cost.
        with session_as(MAKER):
            order = new_doc('Sales Order', document_date=date.today(), party=customer, currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'Stock item','quantity':2,'uom':'Each','rate':150}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = get_doc('Sales Order', order.name)
            delivery = create_document_from('Sales Order', order.name, 'Delivery Note', {'warehouse':warehouse.name})
            delivery.submit(ignore_permissions=True)
        assert get_stock_balance(item.name, warehouse.name)['qty'] == Decimal('8.000000')
        assert get_stock_balance(item.name, warehouse.name)['value'] == Decimal('800.00')

        # A partial Sales Return restores one unit and its inventory cost.
        with session_as(MAKER):
            sales_invoice = new_doc('Sales Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(),
                party=customer, currency='NGN', exchange_rate=1, narration='Sale of stock',
                lines=[{'item_code':item.name,'quantity':2,'uom':'Each','valuation_rate':100,'account':revenue,
                        'description':'Stock item','amount':300}]).insert(ignore_permissions=True)
        sales_invoice = approve_and_submit(sales_invoice)
        with session_as(MAKER):
            sales_return = create_document_from('Sales Invoice', sales_invoice.name, 'Sales Return',
                {'warehouse':warehouse.name,'quantities':{sales_invoice.lines[0].name:1}})
        approve_and_submit(sales_return)
        assert get_stock_balance(item.name, warehouse.name)['qty'] == Decimal('9.000000')
        assert get_stock_balance(item.name, warehouse.name)['value'] == Decimal('900.00')

        # Purchase Receipt adds two units; Purchase Return removes one unit.
        with session_as(MAKER):
            purchase_order = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'Stock item','quantity':2,'uom':'Each','rate':100}]).insert(ignore_permissions=True)
            purchase_order.submit(ignore_permissions=True)
            purchase_order = get_doc('Purchase Order', purchase_order.name)
            purchase_receipt = create_document_from('Purchase Order', purchase_order.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            purchase_receipt.submit(ignore_permissions=True)
        assert get_stock_balance(item.name, warehouse.name)['qty'] == Decimal('11.000000')
        with session_as(MAKER):
            purchase_receipt = get_doc('Purchase Receipt', purchase_receipt.name)
            purchase_invoice = create_document_from('Purchase Receipt', purchase_receipt.name, 'Purchase Invoice')
            purchase_invoice.lines[0].account = expense
            purchase_invoice.save(ignore_permissions=True)
        purchase_invoice = approve_and_submit(purchase_invoice)
        with session_as(MAKER):
            purchase_return = create_document_from('Purchase Invoice', purchase_invoice.name, 'Purchase Return',
                {'warehouse':warehouse.name,'quantities':{purchase_invoice.lines[0].name:1}})
        approve_and_submit(purchase_return)
        assert get_stock_balance(item.name, warehouse.name)['qty'] == Decimal('10.000000')
        assert get_stock_balance(item.name, warehouse.name)['value'] == Decimal('1000.00')
    finally:
        velora.shutdown()


def test_purchase_invoice_from_receipt_clears_grni_and_posts_price_variance(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        supplier = __import__('velora').get_list('Supplier', fields=['name'], limit=1)[0]['name']
        expense = __import__('velora').get_list('Account', filters={'account_code':'5000'}, fields=['name'], limit=1)[0]['name']
        from velora_erp.finance.document_flow.conversion import create_document_from
        with session_as(MAKER):
            order = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'GRNI test item','quantity':10,'uom':'Each','rate':100}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = get_doc('Purchase Order', order.name)
            receipt = create_document_from('Purchase Order', order.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt.submit(ignore_permissions=True)
            receipt = get_doc('Purchase Receipt', receipt.name)
            first = create_document_from('Purchase Receipt', receipt.name, 'Purchase Invoice',
                {'quantities':{receipt.lines[0].name:4}})
            first.lines[0].rate = 105  # 4 x 105 = 420
            first.lines[0].account = expense
            first.save(ignore_permissions=True)
        first = approve_and_submit(first)
        # Four units at receipt value 400; invoice value 420; variance debit 20.
        rows = __import__('velora').get_list('Account Ledger Record', filters={'source_name':first.name}, fields=['account','debit','credit'])
        grni_debit = sum((Decimal(str(r['debit'] or 0)) for r in rows if r['account']==grni.name), Decimal('0'))
        assert grni_debit == Decimal('400.00')
        ppv = __import__('velora').get_list('Account', filters={'account_code':'5300'}, fields=['name'], limit=1)[0]['name']
        ppv_debit = sum((Decimal(str(r['debit'] or 0)) for r in rows if r['account']==ppv), Decimal('0'))
        assert ppv_debit == Decimal('20.00')
        with session_as(MAKER):
            second = create_document_from('Purchase Receipt', receipt.name, 'Purchase Invoice')
            assert Decimal(str(second.lines[0].quantity)) == Decimal('6')
            second.lines[0].account = expense
            second.save(ignore_permissions=True)
        second = approve_and_submit(second)
        # The second invoice clears the remaining GRNI; no over-invoicing is possible.
        rows = __import__('velora').get_list('Account Ledger Record', filters={'source_name':second.name}, fields=['account','debit','credit'])
        grni_debit_second = sum((Decimal(str(r['debit'] or 0)) for r in rows if r['account']==grni.name), Decimal('0'))
        assert grni_debit_second == Decimal('600.00')
        with session_as(MAKER):
            with pytest.raises(ValidationError, match='already been invoiced'):
                create_document_from('Purchase Receipt', receipt.name, 'Purchase Invoice')
    finally:
        velora.shutdown()


def test_stock_transfer_preserves_quantity_and_carrying_value(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        from velora_erp.finance.inventory.ledger import get_stock_balance
        destination = new_doc('Warehouse', warehouse_name='Secondary Store', is_group=0, disabled=0).insert(ignore_permissions=True)
        with session_as(MAKER):
            recon = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                items=[{'item_code':item.name,'physical_qty':12,'proposed_rate':125}]).insert(ignore_permissions=True)
        approve_and_submit(recon)
        with session_as(MAKER):
            transfer = new_doc('Stock Transfer', posting_date=date.today(), source_warehouse=warehouse.name,
                target_warehouse=destination.name, approval_status='Pending',
                lines=[{'item_code':item.name,'quantity':5,'uom':'Each'}]).insert(ignore_permissions=True)
        transfer = approve_and_submit(transfer)
        source = get_stock_balance(item.name, warehouse.name)
        target = get_stock_balance(item.name, destination.name)
        assert source['qty'] == Decimal('7.000000')
        assert target['qty'] == Decimal('5.000000')
        assert source['value'] + target['value'] == Decimal('1500.00')
        assert target['rate'] == Decimal('125')
        from velora_erp.finance.inventory.ledger import get_stock_balances
        balances = get_stock_balances(item_code=item.name)
        assert {row['warehouse']: row['qty'] for row in balances} == {
            warehouse.name: Decimal('7.000000'), destination.name: Decimal('5.000000')
        }
        assert not transfer.get('posting_batch')
    finally:
        velora.shutdown()


def test_fifo_valuation_consumes_oldest_cost_layers_and_updates_stock_value(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        from velora_erp.finance.inventory.ledger import get_stock_balance
        fifo_item = new_doc('Inventory Item', name='ITEM-FIFO-1', item_name='FIFO Stock Item', stock_uom='Each',
            tracking_mode='None', valuation_method='FIFO', standard_rate=100).insert(ignore_permissions=True)
        with session_as(MAKER):
            opening = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                items=[{'item_code':fifo_item.name,'physical_qty':10,'proposed_rate':100}]).insert(ignore_permissions=True)
        approve_and_submit(opening)
        supplier = __import__('velora').get_list('Supplier', fields=['name'], limit=1)[0]['name']
        customer = __import__('velora').get_list('Customer', fields=['name'], limit=1)[0]['name']
        expense = __import__('velora').get_list('Account', filters={'account_code':'5000'}, fields=['name'], limit=1)[0]['name']
        revenue = __import__('velora').get_list('Account', filters={'account_code':'4000'}, fields=['name'], limit=1)[0]['name']
        from velora_erp.finance.document_flow.conversion import create_document_from
        with session_as(MAKER):
            po = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO item','quantity':10,'uom':'Each','rate':200}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            receipt = create_document_from('Purchase Order', po.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt.submit(ignore_permissions=True)
            so = new_doc('Sales Order', document_date=date.today(), party=customer, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO item','quantity':12,'uom':'Each','rate':300}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            delivery = create_document_from('Sales Order', so.name, 'Delivery Note', {'warehouse':warehouse.name})
            delivery.submit(ignore_permissions=True)
        balance = get_stock_balance(fifo_item.name, warehouse.name)
        assert balance['qty'] == Decimal('8.000000')
        assert balance['value'] == Decimal('1600.00')
        rows = __import__('velora').get_list('Stock Ledger Record', filters={'voucher_type':'Delivery Note','voucher_no':delivery.name},
            fields=['actual_qty','stock_value_difference'])
        assert sum((Decimal(str(r['stock_value_difference'])) for r in rows), Decimal('0')) == Decimal('-1400.00')
    finally:
        velora.shutdown()


def test_fifo_layer_calculation_and_periodic_weighted_average_close_math():
    from velora_erp.finance.inventory.valuation import fifo_consume, periodic_weighted_average
    layers = [
        {'qty':Decimal('10'), 'value':Decimal('1000.00'), 'date':'2026-01-01'},
        {'qty':Decimal('10'), 'value':Decimal('2000.00'), 'date':'2026-01-02'},
    ]
    cost, allocations, remaining = fifo_consume(layers, Decimal('12'))
    assert cost == Decimal('1400.00')
    assert [row['qty'] for row in allocations] == [Decimal('10'), Decimal('2')]
    assert remaining[0]['qty'] == Decimal('8')
    assert remaining[0]['value'] == Decimal('1600.00')
    result = periodic_weighted_average(10, 1000, [
        {'actual_qty':-5, 'stock_value_difference':-500},
        {'actual_qty':10, 'stock_value_difference':2000},
    ])
    assert result['weighted_average_rate'] == Decimal('150')
    assert result['closing_qty'] == Decimal('15')
    assert result['target_closing_value'] == Decimal('2250.00')
    assert result['valuation_adjustment'] == Decimal('-250.00')


def _configure_opening_stock_clearing_account():
    equity_group = new_doc('Account Group', group_code='OPEN-EQ', group_name='Opening Balances', root_type='Equity', is_group=0).insert(ignore_permissions=True)
    clearing = new_doc('Account', account_code='3100', account_name='Opening Stock Clearing', account_group=equity_group.name,
        account_type='EQUITY', allow_manual_posting=1).insert(ignore_permissions=True)
    settings = get_doc('Inventory Settings', 'Primary Inventory Settings')
    settings.opening_balance_clearing_account = clearing.name
    settings.save(ignore_permissions=True)
    return clearing


def test_opening_stock_entry_and_stock_revaluation_post_controlled_value_adjustments(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        _configure_opening_stock_clearing_account()
        stock_item = new_doc('Inventory Item', name='ITEM-OPEN-1', item_name='Opening Stock Item', stock_uom='Each',
            tracking_mode='None', valuation_method='FIFO', standard_rate=100).insert(ignore_permissions=True)
        with session_as(MAKER):
            opening = new_doc('Opening Stock Entry', posting_date=date.today(), remarks='Migration opening balance',
                items=[{'item_code':stock_item.name,'warehouse':warehouse.name,'quantity':10,'valuation_rate':100}]).insert(ignore_permissions=True)
        opening = approve_and_submit(opening)
        balance = get_stock_balance(stock_item.name, warehouse.name)
        assert balance['qty'] == Decimal('10.000000')
        assert balance['value'] == Decimal('1000.00')
        assert opening.inventory_posting_batch
        with session_as(MAKER):
            revaluation = new_doc('Stock Revaluation', posting_date=date.today(), remarks='Approved price update',
                items=[{'item_code':stock_item.name,'warehouse':warehouse.name,'proposed_rate':120}]).insert(ignore_permissions=True)
        revaluation = approve_and_submit(revaluation)
        balance = get_stock_balance(stock_item.name, warehouse.name)
        assert balance['qty'] == Decimal('10.000000')
        assert balance['value'] == Decimal('1200.00')
        assert revaluation.inventory_posting_batch
    finally:
        velora.shutdown()


def test_periodic_weighted_average_closing_adjusts_inventory_and_blocks_closed_period(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        _configure_opening_stock_clearing_account()
        weighted_item = new_doc('Inventory Item', name='ITEM-WAVG-1', item_name='Periodic Weighted Item', stock_uom='Each',
            tracking_mode='None', valuation_method='Weighted Average', standard_rate=100).insert(ignore_permissions=True)
        yesterday = date.today().fromordinal(date.today().toordinal() - 1)
        with session_as(MAKER):
            opening = new_doc('Opening Stock Entry', posting_date=yesterday, remarks='Opening balance before period',
                items=[{'item_code':weighted_item.name,'warehouse':warehouse.name,'quantity':10,'valuation_rate':100}]).insert(ignore_permissions=True)
        approve_and_submit(opening)
        customer = __import__('velora').get_list('Customer', fields=['name'], limit=1)[0]['name']
        supplier = __import__('velora').get_list('Supplier', fields=['name'], limit=1)[0]['name']
        revenue = __import__('velora').get_list('Account', filters={'account_code':'4000'}, fields=['name'], limit=1)[0]['name']
        expense = __import__('velora').get_list('Account', filters={'account_code':'5000'}, fields=['name'], limit=1)[0]['name']
        from velora_erp.finance.document_flow.conversion import create_document_from
        with session_as(MAKER):
            so = new_doc('Sales Order', document_date=date.today(), party=customer, currency='NGN', exchange_rate=1,
                lines=[{'item_code':weighted_item.name,'description':'Weighted item','quantity':5,'uom':'Each','rate':200}]).insert(ignore_permissions=True)
            so.submit(ignore_permissions=True)
            delivery = create_document_from('Sales Order', so.name, 'Delivery Note', {'warehouse':warehouse.name})
            delivery.submit(ignore_permissions=True)
            po = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':weighted_item.name,'description':'Weighted item','quantity':10,'uom':'Each','rate':200}]).insert(ignore_permissions=True)
            po.submit(ignore_permissions=True)
            receipt = create_document_from('Purchase Order', po.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt.submit(ignore_permissions=True)
        # Before period close, the issue was provisionally costed at 100 per unit.
        before = get_stock_balance(weighted_item.name, warehouse.name)
        assert before['qty'] == Decimal('15.000000')
        assert before['value'] == Decimal('2500.00')
        with session_as(MAKER):
            closing = new_doc('Inventory Valuation Closing', period_start=date.today(), period_end=date.today(),
                posting_date=date.today(), warehouse=warehouse.name, remarks='Monthly weighted average close').insert(ignore_permissions=True)
        closing = approve_and_submit(closing)
        after = get_stock_balance(weighted_item.name, warehouse.name)
        assert after['qty'] == Decimal('15.000000')
        assert after['value'] == Decimal('2250.00')
        assert closing.total_value_adjustment == -250
        assert closing.inventory_posting_batch
        with session_as(MAKER):
            with pytest.raises(ValidationError, match='period is closed'):
                new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                    items=[{'item_code':weighted_item.name,'physical_qty':15,'proposed_rate':150}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_fifo_landed_cost_targets_original_receipt_layer_and_transfer_preserves_layers(tmp_path):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        fifo_item = new_doc('Inventory Item', name='ITEM-FIFO-LC', item_name='FIFO Landed Cost Item', stock_uom='Each',
            tracking_mode='None', valuation_method='FIFO', standard_rate=100).insert(ignore_permissions=True)
        supplier = __import__('velora').get_list('Supplier', fields=['name'], limit=1)[0]['name']
        customer = __import__('velora').get_list('Customer', fields=['name'], limit=1)[0]['name']
        revenue = __import__('velora').get_list('Account', filters={'account_code':'4000'}, fields=['name'], limit=1)[0]['name']
        from velora_erp.finance.document_flow.conversion import create_document_from
        with session_as(MAKER):
            po1 = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO A','quantity':10,'uom':'Each','rate':100}]).insert(ignore_permissions=True)
            po1.submit(ignore_permissions=True)
            receipt1 = create_document_from('Purchase Order', po1.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt1.submit(ignore_permissions=True)
            so1 = new_doc('Sales Order', document_date=date.today(), party=customer, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO issue','quantity':5,'uom':'Each','rate':300}]).insert(ignore_permissions=True)
            so1.submit(ignore_permissions=True)
            delivery1 = create_document_from('Sales Order', so1.name, 'Delivery Note', {'warehouse':warehouse.name})
            delivery1.submit(ignore_permissions=True)
            po2 = new_doc('Purchase Order', document_date=date.today(), party=supplier, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO B','quantity':10,'uom':'Each','rate':200}]).insert(ignore_permissions=True)
            po2.submit(ignore_permissions=True)
            receipt2 = create_document_from('Purchase Order', po2.name, 'Purchase Receipt', {'warehouse':warehouse.name})
            receipt2.submit(ignore_permissions=True)
            receipt1 = get_doc('Purchase Receipt', receipt1.name)
            voucher = new_doc('Landed Cost Voucher', voucher_date=date.today(), purchase_receipt=receipt1.name,
                currency='NGN', exchange_rate=1, allocation_method='By Value', narration='Freight for first receipt',
                charges=[{'description':'Freight','charge_account':'5000','amount':100}],
                allocations=[{'item_code':fifo_item.name,'source_line':receipt1.lines[0].name,'quantity':10,'item_value':1000}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            voucher = get_doc('Landed Cost Voucher', voucher.name)
            voucher.approval_status = 'Approved'; voucher.save(ignore_permissions=True); voucher.submit(ignore_permissions=True)
        balance = get_stock_balance(fifo_item.name, warehouse.name)
        assert balance['qty'] == Decimal('15.000000')
        assert balance['value'] == Decimal('2550.00')
        destination = new_doc('Warehouse', warehouse_name='FIFO Transfer Store', is_group=0, disabled=0).insert(ignore_permissions=True)
        with session_as(MAKER):
            transfer = new_doc('Stock Transfer', posting_date=date.today(), source_warehouse=warehouse.name,
                target_warehouse=destination.name, approval_status='Pending',
                lines=[{'item_code':fifo_item.name,'quantity':6,'uom':'Each'}]).insert(ignore_permissions=True)
        approve_and_submit(transfer)
        target_balance = get_stock_balance(fifo_item.name, destination.name)
        assert target_balance['qty'] == Decimal('6.000000')
        assert target_balance['value'] == Decimal('750.00')
        with session_as(MAKER):
            so2 = new_doc('Sales Order', document_date=date.today(), party=customer, currency='NGN', exchange_rate=1,
                lines=[{'item_code':fifo_item.name,'description':'FIFO transfer issue','quantity':6,'uom':'Each','rate':300}]).insert(ignore_permissions=True)
            so2.submit(ignore_permissions=True)
            delivery2 = create_document_from('Sales Order', so2.name, 'Delivery Note', {'warehouse':destination.name})
            delivery2.submit(ignore_permissions=True)
        issue_rows = __import__('velora').get_list('Stock Ledger Record', filters={'voucher_type':'Delivery Note','voucher_no':delivery2.name},
            fields=['stock_value_difference'])
        assert sum((Decimal(str(row['stock_value_difference'])) for row in issue_rows), Decimal('0')) == Decimal('-750.00')
        assert get_stock_balance(fifo_item.name, destination.name)['qty'] == Decimal('0.000000')
    finally:
        velora.shutdown()


def _grni_net(grni):
    rows = get_list("Account Ledger Record", filters={"account": grni.name}, fields=["base_debit", "base_credit"], limit=1000)
    return sum(Decimal(str(r["base_credit"] or 0)) - Decimal(str(r["base_debit"] or 0)) for r in rows)


def _receive_and_invoice(tmp_path, quantity, rate, conversion_factor, invoice_quantity=None):
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    supplier = get_list("Supplier", fields=["name"], limit=1)[0]["name"]
    with session_as(MAKER):
        order = new_doc("Purchase Order", document_date=date.today(), party=supplier, currency="NGN", exchange_rate=1,
                        lines=[{"item_code": item.name, "description": "x", "quantity": quantity, "uom": "Each",
                                "rate": rate, "conversion_factor": conversion_factor}]).insert(ignore_permissions=True)
        order.submit(ignore_permissions=True)
        receipt = create_document_from("Purchase Order", order.name, "Purchase Receipt", {"warehouse": warehouse.name})
        receipt.submit(ignore_permissions=True)
        overrides = {"quantities": {}} if invoice_quantity is None else {"quantities": {"1": invoice_quantity}}
        invoice = create_document_from("Purchase Receipt", receipt.name, "Purchase Invoice")
        invoice.lines[0].account = get_list("Account", filters={"account_code": "5000"}, fields=["name"], limit=1)[0]["name"]
        invoice.save(ignore_permissions=True)
    return grni, receipt, invoice


def test_grni_is_cleared_when_receipt_uses_a_uom_conversion_factor(tmp_path):
    """Regression: the invoice built from a receipt dropped the UOM conversion factor, so GRNI was cleared for the wrong
    quantity and Stock Received But Not Billed kept a balance."""
    try:
        grni, receipt, invoice = _receive_and_invoice(tmp_path, 7, "100.50", 12)
        assert Decimal(str(invoice.lines[0].conversion_factor)) == Decimal("12")
        approve_and_submit(invoice)
        assert _grni_net(grni) == 0
    finally:
        velora.shutdown()


def test_preview_entry_shows_posted_and_draft_entries_balanced(tmp_path):
    from velora_erp.finance.entry_preview import preview_entries
    try:
        grni, receipt, invoice = _receive_and_invoice(tmp_path, 7, "100.50", 12)
        draft = preview_entries("Purchase Invoice", invoice.name)
        assert draft["status"] == "Preview" and draft["balanced"] and len(draft["rows"]) >= 2
        assert any("Clear GRNI" in (r["description"] or "") for r in draft["rows"])
        approve_and_submit(invoice)
        posted = preview_entries("Purchase Invoice", invoice.name)
        assert posted["status"] == "Posted" and posted["balanced"]
        assert Decimal(posted["total_debit"]) == Decimal(draft["total_debit"])
        assert preview_entries("Purchase Receipt", receipt.name)["status"] == "Posted"
        assert all(r["account_label"] for r in posted["rows"])
    finally:
        velora.shutdown()
