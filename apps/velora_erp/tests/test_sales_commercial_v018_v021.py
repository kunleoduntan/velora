import json
from pathlib import Path
import pytest
import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).parents[1] / "velora_erp" / "finance"


def _meta(path):
    return json.loads((ROOT / "doctype" / path).read_text())


def test_sales_order_invoice_conversion_is_registered_and_line_accounted():
    registry = (ROOT / "document_flow" / "registry.py").read_text()
    assert 'DocumentFlow("Sales Order", "Sales Invoice", "Create Sales Invoice", "active", "sales_order_invoice", "one_to_many"' in registry
    order_line = {f["fieldname"] for f in _meta("sales_order_line/sales_order_line.json")["fields"]}
    invoice = {f["fieldname"] for f in _meta("sales_invoice/sales_invoice.json")["fields"]}
    invoice_line = {f["fieldname"] for f in _meta("sales_invoice_line/sales_invoice_line.json")["fields"]}
    assert {"revenue_account", "tax_account", "tax_rate"} <= order_line
    assert {"source_doctype", "source_document"} <= invoice
    assert {"source_line", "conversion_factor", "cost_rate", "cost_source"} <= invoice_line
    assert (ROOT / "document_flow" / "sales_invoicing.py").exists()


def test_credit_control_is_server_enforced_and_reported():
    customer = {f["fieldname"] for f in _meta("customer/customer.json")["fields"]}
    settings = {f["fieldname"] for f in _meta("finance_settings/finance_settings.json")["fields"]}
    assert {"credit_limit", "credit_hold", "credit_hold_reason"} <= customer
    assert {"enforce_customer_credit_limit", "include_open_sales_orders_in_credit_exposure"} <= settings
    controller = (ROOT / "doctype" / "sales_order" / "sales_order.py").read_text()
    invoice_controller = (ROOT / "doctype" / "sales_invoice" / "sales_invoice.py").read_text()
    assert "enforce_customer_credit" in controller and "enforce_customer_credit" in invoice_controller
    assert (ROOT / "report" / "customer_credit_exposure" / "customer_credit_exposure.py").exists()


def test_delivery_note_records_realised_issue_cost_for_margin_reporting():
    fields = {f["fieldname"] for f in _meta("delivery_note_line/delivery_note_line.json")["fields"]}
    assert {"issue_cost_rate", "issue_cost_amount"} <= fields
    ledger = (ROOT / "inventory" / "ledger.py").read_text()
    report = (ROOT / "report" / "sales_margin_analysis" / "sales_margin_analysis.py").read_text()
    assert "line.issue_cost_rate = rate" in ledger
    assert "Realised Delivery Note issue cost" in report


def test_sales_return_conversion_and_disposition_controls():
    registry = (ROOT / "document_flow" / "registry.py").read_text()
    assert 'DocumentFlow("Sales Invoice", "Sales Return", "Create Sales Return", "active"' in registry
    ret = {f["fieldname"]: f for f in _meta("sales_return/sales_return.json")["fields"]}
    assert ret["return_disposition"]["options"] == ["Restock", "Quarantine"]
    assert "quality_inspection_status" in ret
    warehouse = {f["fieldname"] for f in _meta("warehouse/warehouse.json")["fields"]}
    assert "is_quarantine_warehouse" in warehouse
    assert (ROOT / "document_flow" / "sales_returns.py").exists()


def test_customer_complaint_is_registered_as_auditable_doctype():
    path = ROOT / "doctype" / "customer_complaint" / "customer_complaint.json"
    meta = json.loads(path.read_text())
    fields = {f["fieldname"] for f in meta["fields"]}
    assert {"customer", "sales_invoice", "delivery_note", "category", "severity", "resolution_status", "resolution", "related_return", "related_replacement_order"} <= fields
    assert meta["track_changes"] is True


def test_sales_order_to_invoice_conversion_preserves_source_price_and_partial_quantities(tmp_path):
    import velora
    from datetime import date
    from velora import new_doc
    from velora.permissions import session_as
    from velora.exceptions import ValidationError
    from velora_erp.finance.document_flow.conversion import create_document_from
    from test_document_flow import setup_flow, MAKER
    try:
        bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
        with session_as(MAKER):
            order = new_doc('Sales Order', document_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1,
                lines=[{'item_code':'SERVICE-01','description':'Implementation service','quantity':10,'uom':'Hour','rate':125,
                        'discount_percentage':10,'revenue_account':revenue.name}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            order = velora.get_doc('Sales Order', order.name)
            source_line = order.lines[0].name
            first = create_document_from('Sales Order', order.name, 'Sales Invoice', {'quantities':{source_line:4}})
            second = create_document_from('Sales Order', order.name, 'Sales Invoice', {'quantities':{source_line:6}})
            assert first.lines[0].quantity == 4
            assert second.lines[0].quantity == 6
            assert first.lines[0].rate == 125
            assert first.lines[0].amount == 450
            assert first.source_document == order.name
            with pytest.raises(ValidationError):
                create_document_from('Sales Order', order.name, 'Sales Invoice', {'quantities':{source_line:1}})
    finally:
        velora.shutdown()


def test_customer_credit_limit_blocks_order_submission(tmp_path):
    import velora
    from datetime import date
    from velora import new_doc, get_doc
    from velora.permissions import session_as
    from velora.exceptions import ValidationError
    from test_document_flow import setup_flow, MAKER
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            party = get_doc("Customer", customer.name)
            party.credit_limit = 100
            party.save(ignore_permissions=True)
            order = new_doc('Sales Order', document_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1,
                lines=[{'description':'Consulting','quantity':2,'uom':'Hour','rate':100}]).insert(ignore_permissions=True)
            with pytest.raises(ValidationError, match='credit limit'):
                order.submit(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_sales_return_create_from_invoice_uses_remaining_quantities(tmp_path):
    import velora
    from datetime import date
    from velora import new_doc, get_doc
    from velora.permissions import session_as
    from velora.exceptions import ValidationError
    from test_document_flow import setup_flow, MAKER, APPROVER
    from velora_erp.finance.document_flow.conversion import create_document_from
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        with session_as(MAKER):
            invoice = new_doc('Sales Invoice', invoice_date=date.today(), posting_date=date.today(), due_date=date.today(),
                party=customer.name, currency='NGN', exchange_rate=1, narration='Service delivery',
                lines=[{'item_code':'SERVICE-RET','quantity':5,'uom':'Hour','account':revenue.name,'description':'Consulting',
                        'rate':100,'amount':500,'tax_rate':0,'tax_amount':0}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            invoice=get_doc('Sales Invoice',invoice.name); invoice.approval_status='Approved'; invoice.save(ignore_permissions=True); invoice.submit(ignore_permissions=True)
        with session_as(MAKER):
            invoice=get_doc('Sales Invoice',invoice.name)
            source_line=invoice.lines[0].name
            ret=create_document_from('Sales Invoice',invoice.name,'Sales Return',{'quantities':{source_line:2}})
            assert ret.source_invoice == invoice.name
            assert ret.lines[0].quantity == 2
            assert ret.lines[0].amount == 200
            with pytest.raises(ValidationError):
                create_document_from('Sales Invoice',invoice.name,'Sales Return',{'quantities':{source_line:4}})
    finally:
        velora.shutdown()


def test_stock_sales_invoice_quantity_cannot_exceed_submitted_delivery(tmp_path):
    import velora
    from datetime import date
    from velora import new_doc, get_doc, get_list
    from velora.permissions import session_as
    from velora.exceptions import ValidationError
    from velora_erp.finance.document_flow.conversion import create_document_from
    from test_inventory_v012 import setup_inventory, approve_and_submit, MAKER
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        with session_as(MAKER):
            reconciliation = new_doc('Stock Reconciliation', posting_date=date.today(), warehouse=warehouse.name,
                remarks='Initial stock for invoice delivery gate', items=[{'item_code':item.name,'physical_qty':10,'proposed_rate':100}]).insert(ignore_permissions=True)
        approve_and_submit(reconciliation)
        customer = get_doc('Customer','C001')
        revenue = get_list('Account',filters={'account_code':'4000'},fields=['name'],limit=1)[0]['name']
        with session_as(MAKER):
            order = new_doc('Sales Order', document_date=date.today(), party=customer.name, currency='NGN', exchange_rate=1,
                lines=[{'item_code':item.name,'description':'Test stock item','quantity':5,'uom':'Each','conversion_factor':1,
                        'rate':150,'revenue_account':revenue}]).insert(ignore_permissions=True)
            order.submit(ignore_permissions=True)
            with pytest.raises(ValidationError, match="billable Sales Order quantities"):
                create_document_from('Sales Order',order.name,'Sales Invoice',{})
            source_line=order.lines[0].name
            delivery=create_document_from('Sales Order',order.name,'Delivery Note',{'quantities':{source_line:3},'warehouse':warehouse.name})
            delivery.submit(ignore_permissions=True)
            delivery = get_doc("Delivery Note", delivery.name)
            assert delivery.lines[0].issue_cost_amount == 300
            assert delivery.lines[0].issue_cost_rate == 100
            invoice=create_document_from('Sales Order',order.name,'Sales Invoice',{'quantities':{source_line:2}})
            assert invoice.lines[0].quantity==2
            with pytest.raises(ValidationError):
                create_document_from('Sales Order',order.name,'Sales Invoice',{'quantities':{source_line:2}})
        from test_document_flow import APPROVER
        with session_as(APPROVER):
            invoice=get_doc("Sales Invoice",invoice.name)
            invoice.approval_status="Approved"
            invoice.save(ignore_permissions=True)
            invoice.submit(ignore_permissions=True)
        from velora_erp.finance.report.sales_margin_analysis.sales_margin_analysis import execute as margin_report
        with session_as(MAKER):
            report=margin_report({"from_date":date.today().isoformat(),"to_date":date.today().isoformat()})
            realised=[row.values for row in report.rows if row.values.get("sales_invoice")==invoice.name]
            assert len(realised)==1
            assert realised[0]["cost_status"]=="Realised Delivery Note issue cost"
            assert realised[0]["cost_base"]==200
            assert realised[0]["gross_profit_base"]==100
    finally:
        velora.shutdown()
