"""Goods in transit, reservations, quality inspection, quotations, cycle counts and batch expiry (v2.85)."""
from datetime import date, timedelta
from types import SimpleNamespace
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from test_inventory_v012 import setup_inventory, approve_and_submit, session_as, MAKER
from velora_erp.finance.inventory.ledger import get_stock_balance
from velora_erp.finance.inventory import transit, reservations, quality, procurement, cycle_count, expiry
from velora_erp.finance.document_flow.conversion import create_document_from


def stock(item, warehouse, qty, rate=100):
    with session_as(MAKER):
        rec = new_doc("Stock Reconciliation", posting_date=date.today(), warehouse=warehouse.name,
                      items=[{"item_code": item.name, "physical_qty": qty, "proposed_rate": rate}]).insert(ignore_permissions=True)
    approve_and_submit(rec)


def test_transfer_via_transit_then_partial_and_full_receipt(tmp_path):
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        stock(item, wh, 10)
        dest = new_doc("Warehouse", warehouse_name="Branch", is_group=0, disabled=0).insert(ignore_permissions=True)
        via = new_doc("Warehouse", warehouse_name="On the Road", is_group=0, disabled=0, is_transit=1).insert(ignore_permissions=True)
        with session_as(MAKER):
            tr = new_doc("Stock Transfer", posting_date=date.today(), source_warehouse=wh.name, target_warehouse=dest.name, transit_warehouse=via.name,
                         approval_status="Pending", lines=[{"item_code": item.name, "quantity": 6, "uom": "Each"}]).insert(ignore_permissions=True)
        tr = approve_and_submit(tr)
        assert tr.transit_status == "In Transit"
        assert get_stock_balance(item.name, wh.name)["qty"] == 4
        assert get_stock_balance(item.name, via.name)["qty"] == 6
        assert get_stock_balance(item.name, dest.name)["qty"] == 0
        assert transit.transit_rows()[0]["in_transit"] == 6
        rc = create_document_from("Stock Transfer", tr.name, "Stock Transfer Receipt")
        rc.lines[0].quantity = 2
        rc.save(ignore_permissions=True)
        approve_and_submit(rc)
        assert get_doc("Stock Transfer", tr.name, ignore_permissions=True).transit_status == "Partially Received"
        assert get_stock_balance(item.name, dest.name)["qty"] == 2
        rc2 = create_document_from("Stock Transfer", tr.name, "Stock Transfer Receipt")
        assert rc2.lines[0].quantity == 4
        rc2.lines[0].quantity = 5
        with pytest.raises(ValidationError):
            rc2.save(ignore_permissions=True)
        rc2.lines[0].quantity = 4
        rc2.save(ignore_permissions=True)
        approve_and_submit(rc2)
        assert get_doc("Stock Transfer", tr.name, ignore_permissions=True).transit_status == "Received"
        assert get_stock_balance(item.name, via.name)["qty"] == 0 and get_stock_balance(item.name, dest.name)["qty"] == 6
        assert transit.transit_rows() == []
    finally:
        velora.shutdown()


def test_transit_warehouse_rules(tmp_path):
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        stock(item, wh, 5)
        dest = new_doc("Warehouse", warehouse_name="Branch", is_group=0, disabled=0).insert(ignore_permissions=True)
        plain = new_doc("Warehouse", warehouse_name="Plain", is_group=0, disabled=0).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="not a transit"):
            new_doc("Stock Transfer", posting_date=date.today(), source_warehouse=wh.name, target_warehouse=dest.name, transit_warehouse=plain.name,
                    lines=[{"item_code": item.name, "quantity": 1, "uom": "Each"}]).insert(ignore_permissions=True)
    finally:
        velora.shutdown()


def test_reservation_blocks_other_issues_and_is_used_by_its_own_document(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    try:
        stock(item, wh, 10)
        res = new_doc("Stock Reservation", item_code=item.name, warehouse=wh.name, quantity=7, reserved_for_doctype="Sales Order", reserved_for="SO-1").insert(ignore_permissions=True)
        assert reservations.available(item.name, wh.name) == 3
        with pytest.raises(ValidationError, match="Only 3"):
            new_doc("Stock Reservation", item_code=item.name, warehouse=wh.name, quantity=4).insert(ignore_permissions=True)
        issue = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=wh.name,
                        lines=[{"item_code": item.name, "quantity": 5, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="reserved"):
            issue.submit(ignore_permissions=True)
        small = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=wh.name,
                        lines=[{"item_code": item.name, "quantity": 3, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        small.submit(ignore_permissions=True)
        assert reservations.available(item.name, wh.name) == 0
        # the document the stock is reserved for may issue it
        src = SimpleNamespace(doctype="Delivery Note", name="DN-1", source_doctype="Sales Order", source_document="SO-1")
        reservations.assert_unreserved(src, item.name, wh.name, None, 7)
        reservations.consume(src, item.name, wh.name, None, 7)
        got = get_doc("Stock Reservation", res.name, ignore_permissions=True)
        assert got.status == "Fulfilled" and float(got.consumed_quantity) == 7
        rel = new_doc("Stock Reservation", item_code=item.name, warehouse=wh.name, quantity=1, reserved_until=date.today() + timedelta(days=1)).insert(ignore_permissions=True)
        rel.reserved_until = date.today() - timedelta(days=1)
        from velora import db
        from sqlalchemy import update
        from velora.db.tables import get_table
        t = get_table("Stock Reservation")
        with db.transaction() as c:
            c.execute(update(t).where(t.c.name == rel.name).values(reserved_until=date.today() - timedelta(days=1)))
        assert reservations.expire_due() == 1
        assert get_doc("Stock Reservation", rel.name, ignore_permissions=True).status == "Expired"
        assert reservations.availability_rows(wh.name)
    finally:
        velora.shutdown()


def test_quality_inspection_readings_and_gate(tmp_path):
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        new_doc("Quality Inspection Template", template_name="Bolt Check", parameters=[
            {"parameter": "Length", "kind": "Numeric", "min_value": 9, "max_value": 11, "unit": "mm"}, {"parameter": "Finish", "kind": "Pass/Fail"}]).insert(ignore_permissions=True)
        it = get_doc("Inventory Item", item.name, ignore_permissions=True)
        it.inspection_required_on_receipt = 1; it.quality_inspection_template = "Bolt Check"; it.save(ignore_permissions=True)
        grn = SimpleNamespace(doctype="Purchase Receipt", name="PR-X", lines=[SimpleNamespace(item_code=item.name, quantity=5, batch=None)])
        with pytest.raises(ValidationError, match="must be quality-inspected"):
            quality.require_inspections(grn, "inspection_required_on_receipt")
        # a real draft receipt is not needed to test readings: validate the document rules directly
        doc = SimpleNamespace(doctype="Quality Inspection", readings=[], template="Bolt Check", inspected_quantity=5, result="Accepted", accepted_quantity=0, rejected_quantity=0, inspector=None,
                              append=lambda f, r: doc.readings.append(SimpleNamespace(**{"reading": None, "passed": 0, "outcome": None, **r})), _link_children=lambda: None)
        quality.prepare(doc)
        doc.readings[0].reading = 12; doc.readings[1].passed = 1
        quality.prepare(doc)
        assert doc.result == "Rejected" and doc.rejected_quantity == 5 and doc.accepted_quantity == 0
        doc.readings[0].reading = 10; doc.result = "Accepted"
        quality.prepare(doc)
        assert doc.result == "Accepted" and doc.accepted_quantity == 5
    finally:
        velora.shutdown()


def test_request_for_quotation_to_award(tmp_path):
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        ap = get_doc("Supplier", "S001", ignore_permissions=True).control_account
        s1 = new_doc("Supplier", supplier_code="ALPHA", supplier_name="Alpha Supplies", supplier_group="SG", supplier_type="Company", control_account=ap).insert(ignore_permissions=True)
        s2 = new_doc("Supplier", supplier_code="BETA", supplier_name="Beta Supplies", supplier_group="SG", supplier_type="Company", control_account=ap).insert(ignore_permissions=True)
        mr = new_doc("Material Request", request_type="Purchase", request_date=date.today(), target_warehouse=wh.name, required_by=date.today() + timedelta(days=10),
                     lines=[{"item_code": item.name, "quantity": 20}]).insert(ignore_permissions=True)
        mr = get_doc("Material Request", mr.name, ignore_permissions=True); mr.request_status = "Approved"; mr.save(ignore_permissions=True)
        rfq = create_document_from("Material Request", mr.name, "Request for Quotation", {"suppliers": [s1.name, s2.name]})
        assert len(rfq.suppliers) == 2 and rfq.items[0].quantity == 20
        q1 = create_document_from("Request for Quotation", rfq.name, "Supplier Quotation", {"supplier": s1.name})
        q1.lines[0].rate = 12; q1.status = "Received"; q1.save(ignore_permissions=True)
        q2 = create_document_from("Request for Quotation", rfq.name, "Supplier Quotation", {"supplier": s2.name})
        q2.lines[0].rate = 10; q2.status = "Received"; q2.save(ignore_permissions=True)
        rows = procurement.comparison_rows(rfq.name)
        assert {r["supplier"]: r["rank"] for r in rows} == {s2.name: 1, s1.name: 2}
        from velora_erp.finance.report.quotation_comparison import quotation_comparison
        assert quotation_comparison.execute({"request_for_quotation": rfq.name}) is not None
        po = create_document_from("Supplier Quotation", q2.name, "Purchase Order", {"expense_account": None})
        assert po.doctype == "Purchase Order"
        assert get_doc("Supplier Quotation", q2.name, ignore_permissions=True).status == "Awarded"
        assert get_doc("Supplier Quotation", q1.name, ignore_permissions=True).status == "Lost"
        with pytest.raises(ValidationError):
            create_document_from("Supplier Quotation", q1.name, "Purchase Order")
    finally:
        velora.shutdown()


def test_cycle_count_generates_by_abc_interval_and_posts_a_reconciliation(tmp_path):
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        stock(item, wh, 10)
        it = get_doc("Inventory Item", item.name, ignore_permissions=True); it.abc_class = "A"; it.save(ignore_permissions=True)
        cc = new_doc("Cycle Count", count_date=date.today(), warehouse=wh.name).insert(ignore_permissions=True)
        assert cc.generate_sheet() == 1
        cc = get_doc("Cycle Count", cc.name, ignore_permissions=True)
        assert cc.status == "Counting" and cc.lines[0].system_qty == 10
        with pytest.raises(ValidationError, match="counted quantity"):
            cc.post_count()
        cc.lines[0].counted_qty = 8
        cc.save(ignore_permissions=True)
        rec = cc.post_count()
        cc = get_doc("Cycle Count", cc.name, ignore_permissions=True)
        assert cc.status == "Posted" and cc.stock_reconciliation == rec and cc.lines[0].variance == -2
        r = get_doc("Stock Reconciliation", rec, ignore_permissions=True)
        assert r.docstatus == 0 and r.items[0].physical_qty == 8 and r.items[0].adjustment_qty == -2
        assert get_stock_balance(item.name, wh.name)["qty"] == 10               # nothing moves until the reconciliation is approved
        assert get_doc("Inventory Item", item.name, ignore_permissions=True).last_counted_on == date.today()
        fresh = new_doc("Cycle Count", count_date=date.today(), warehouse=wh.name).insert(ignore_permissions=True)
        assert fresh.generate_sheet() == 0                                      # counted today, not due again for 30 days
    finally:
        velora.shutdown()


def test_batch_expiry_blocks_issue_and_reports(tmp_path):
    item, wh, inventory, grni, cogs, *_ = setup_inventory(tmp_path)
    try:
        it = get_doc("Inventory Item", item.name, ignore_permissions=True); it.tracking_mode = "Batch"; it.save(ignore_permissions=True)
        old = new_doc("Batch", name="B-OLD", batch_number="B-OLD", item_code=item.name, expiry_date=date.today() - timedelta(days=2)).insert(ignore_permissions=True)
        soon = new_doc("Batch", name="B-SOON", batch_number="B-SOON", item_code=item.name, expiry_date=date.today() + timedelta(days=10)).insert(ignore_permissions=True)
        for b in (old, soon):
            rec = new_doc("Stock Entry", stock_entry_type="Material Receipt", posting_date=date.today(), warehouse=wh.name,
                          lines=[{"item_code": item.name, "quantity": 5, "basic_rate": 10, "batch": b.name}]).insert(ignore_permissions=True)
            rec.submit(ignore_permissions=True)
        rows = {r["batch"]: r["status"] for r in expiry.batch_rows()}
        assert rows == {old.name: "Expired", soon.name: "Expiring soon"}
        dest = new_doc("Warehouse", warehouse_name="Branch", is_group=0, disabled=0).insert(ignore_permissions=True)
        quarantine = new_doc("Warehouse", warehouse_name="Quarantine", is_group=0, disabled=0, is_quarantine_warehouse=1).insert(ignore_permissions=True)
        def move(to, batch):
            with session_as(MAKER):
                t = new_doc("Stock Transfer", posting_date=date.today(), source_warehouse=wh.name, target_warehouse=to.name, approval_status="Pending",
                            lines=[{"item_code": item.name, "quantity": 1, "uom": "Each", "batch": batch}]).insert(ignore_permissions=True)
            return approve_and_submit(t)
        with pytest.raises(ValidationError, match="expired"):
            move(dest, old.name)
        move(quarantine, old.name)                                               # quarantine is allowed
        move(dest, soon.name)                                                    # not yet expired
        scrap = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=wh.name,
                        lines=[{"item_code": item.name, "quantity": 1, "batch": old.name, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        scrap.submit(ignore_permissions=True)                                    # scrapping is allowed
        from velora_erp.finance.report.batch_expiry import batch_expiry
        assert batch_expiry.execute({}) is not None
        assert expiry.watch_expiry() >= 0
    finally:
        velora.shutdown()


def test_material_request_create_from_is_eligible_while_open(tmp_path):
    from velora_erp.finance.document_flow.registry import get_document_flows
    item, wh, *_ = setup_inventory(tmp_path)
    try:
        mr = new_doc("Material Request", request_type="Purchase", request_date=date.today(), target_warehouse=wh.name, lines=[{"item_code": item.name, "quantity": 2}]).insert(ignore_permissions=True)
        assert "Request for Quotation" not in [f["target_doctype"] for f in get_document_flows("Material Request", doc=mr)]   # not approved yet
        mr = get_doc("Material Request", mr.name, ignore_permissions=True); mr.request_status = "Approved"; mr.save(ignore_permissions=True)
        assert "Request for Quotation" in [f["target_doctype"] for f in get_document_flows("Material Request", doc=mr)]
    finally:
        velora.shutdown()


def test_vat_return_report_totals_output_and_input_tax(tmp_path):
    from test_document_flow import setup_flow, APPROVER
    from velora_erp.finance.report.vat_return import vat_return
    bank, customer, supplier, revenue, expense, ar, ap = setup_flow(tmp_path)
    try:
        grp = new_doc("Account Group", group_code="TX", group_name="Taxes", root_type="Liability", is_group=0).insert(ignore_permissions=True)
        vat = new_doc("Account", account_code="2300", account_name="VAT Control", account_group=grp.name, account_type="ACCRUAL", allow_manual_posting=1).insert(ignore_permissions=True)
        inv = new_doc("Sales Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=customer.name, currency="NGN", exchange_rate=1, narration="Taxed",
                      lines=[{"account": revenue.name, "description": "Consulting", "amount": 1000, "tax_account": vat.name, "tax_code": "VAT-STD", "tax_rate": 7.5}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            inv = get_doc("Sales Invoice", inv.name); inv.approval_status = "Approved"; inv.save(ignore_permissions=True); inv.submit(ignore_permissions=True)
        pin = new_doc("Purchase Invoice", invoice_date=date.today(), posting_date=date.today(), due_date=date.today(), party=supplier.name, currency="NGN", exchange_rate=1, narration="Bought",
                      lines=[{"account": expense.name, "description": "Stationery", "amount": 400, "tax_account": vat.name, "tax_code": "VAT-STD", "tax_rate": 7.5}]).insert(ignore_permissions=True)
        with session_as(APPROVER):
            pin = get_doc("Purchase Invoice", pin.name); pin.approval_status = "Approved"; pin.save(ignore_permissions=True); pin.submit(ignore_permissions=True)
        rows = vat_return.vat_rows(date.today() - timedelta(days=1), date.today())
        by = {r["section"]: r for r in rows}
        assert by["Output tax (sales)"]["net"] == 1000 and by["Output tax (sales)"]["tax"] == 75
        assert by["Input tax (purchases)"]["net"] == 400 and by["Input tax (purchases)"]["tax"] == 30
        rb = vat_return.execute({"from_date": date.today() - timedelta(days=1), "to_date": date.today()})
        assert rb is not None
        assert vat_return.vat_rows(date.today() + timedelta(days=1), date.today() + timedelta(days=2)) == []
        with pytest.raises(ValidationError):
            vat_return.execute({"from_date": date.today()})
    finally:
        velora.shutdown()


def test_item_selling_price_follows_cost_and_margin(tmp_path):
    setup_inventory(tmp_path)
    try:
        it = new_doc("Inventory Item", name="WIDGET", item_name="Widget", stock_uom="Each", tracking_mode="None", standard_rate=200, selling_margin_percent=25).insert(ignore_permissions=True)
        assert float(get_doc("Inventory Item", "WIDGET", ignore_permissions=True).calculated_selling_price) == 250
        it = get_doc("Inventory Item", "WIDGET", ignore_permissions=True); it.selling_margin_percent = 10; it.save(ignore_permissions=True)
        assert float(get_doc("Inventory Item", "WIDGET", ignore_permissions=True).calculated_selling_price) == 220
        s = get_list("Inventory Settings", fields=["name"], limit=1, ignore_permissions=True)[0]["name"]
        st = get_doc("Inventory Settings", s, ignore_permissions=True); st.selling_price_basis = "Margin on Selling Price"; st.save(ignore_permissions=True)
        it = get_doc("Inventory Item", "WIDGET", ignore_permissions=True); it.selling_margin_percent = 20; it.save(ignore_permissions=True)
        assert float(get_doc("Inventory Item", "WIDGET", ignore_permissions=True).calculated_selling_price) == 250      # 200 / (1 - 0.20)
        it = get_doc("Inventory Item", "WIDGET", ignore_permissions=True); it.pricing_mode = "Fixed Price"; it.standard_selling_rate = 300; it.save(ignore_permissions=True)
        assert float(get_doc("Inventory Item", "WIDGET", ignore_permissions=True).calculated_selling_price) == 300
    finally:
        velora.shutdown()
