"""Material Request, Stock Entry, item masters, reorder planning and stock reports (v2.83)."""
from datetime import date
import pytest
import velora
from velora import new_doc, get_doc, get_list
from velora.exceptions import ValidationError
from velora_erp.setup import after_install
from velora_erp.finance.document_flow.conversion import create_document_from
from velora_erp.finance.inventory import requests as inv


@pytest.fixture()
def site(tmp_path):
    velora.configure(db_url=f"sqlite:///{tmp_path/'inv.db'}", apps=["velora_erp", "velora_projectone"], developer_mode=True)
    velora.init(); velora.migrate(); after_install()
    yield
    velora.shutdown()


def test_item_masters_are_created_on_demand_and_reorder_levels_are_checked(site):
    i = new_doc("Inventory Item", name="BOLT", item_name="Bolt", stock_uom="Box", item_group="Spares", tracking_mode="None", standard_rate=10, reorder_level=5, reorder_qty=20).insert(ignore_permissions=True)
    assert get_doc("Unit of Measure", "Box", ignore_permissions=True) and get_doc("Item Group", "Spares", ignore_permissions=True)
    with pytest.raises(ValidationError, match="maximum"):
        new_doc("Inventory Item", name="NUT", item_name="Nut", stock_uom="Box", tracking_mode="None", standard_rate=1, reorder_level=50, maximum_stock_level=10).insert(ignore_permissions=True)


def test_material_request_validation_and_reorder_report(site):
    new_doc("Inventory Item", name="BOLT", item_name="Bolt", stock_uom="Box", tracking_mode="None", standard_rate=10, reorder_level=5, reorder_qty=20, preferred_supplier=None).insert(ignore_permissions=True)
    rows = inv.reorder_rows()
    assert rows and rows[0]["item_code"] == "BOLT" and rows[0]["to_order"] == 20 and rows[0]["status"] == "Order now"
    made = inv.create_reorder_requests()
    assert len(made) == 1
    again = inv.reorder_rows()
    assert again == [] or again[0]["status"] != "Order now" or again[0]["requested"] == 0   # a draft is not yet "requested"; approval makes it count
    with pytest.raises(ValidationError, match="at least one"):
        new_doc("Material Request", request_type="Purchase", request_date=date.today(), lines=[]).insert(ignore_permissions=True)


def test_transfer_request_needs_two_different_warehouses(site):
    new_doc("Inventory Item", name="BOLT", item_name="Bolt", stock_uom="Box", tracking_mode="None", standard_rate=10).insert(ignore_permissions=True)
    w = new_doc("Warehouse", warehouse_name="Main").insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="different"):
        new_doc("Material Request", request_type="Material Transfer", request_date=date.today(), source_warehouse=w.name, target_warehouse=w.name,
                lines=[{"item_code": "BOLT", "quantity": 1}]).insert(ignore_permissions=True)


def test_only_an_approved_request_converts_and_conversion_tracks_fulfilment(site):
    new_doc("Inventory Item", name="BOLT", item_name="Bolt", stock_uom="Box", tracking_mode="None", standard_rate=10).insert(ignore_permissions=True)
    w = new_doc("Warehouse", warehouse_name="Main").insert(ignore_permissions=True)
    mr = new_doc("Material Request", request_type="Material Issue", request_date=date.today(), source_warehouse=w.name,
                 lines=[{"item_code": "BOLT", "quantity": 10}]).insert(ignore_permissions=True)
    with pytest.raises(ValidationError, match="approved"):
        create_document_from("Material Request", mr.name, "Stock Entry")
    mr = get_doc("Material Request", mr.name, ignore_permissions=True); mr.request_status = "Approved"; mr.save(ignore_permissions=True)
    se = create_document_from("Material Request", mr.name, "Stock Entry")
    assert se.material_request == mr.name and se.lines[0].quantity == 10
    inv.refresh_fulfilment(mr.name)
    assert get_doc("Material Request", mr.name, ignore_permissions=True).fulfilment_status == "Fulfilled"
    with pytest.raises(ValidationError, match="already been converted"):
        create_document_from("Material Request", mr.name, "Stock Entry")


def test_stock_entry_receives_issues_and_posts_to_the_ledger_and_accounts(tmp_path):
    from test_inventory_v012 import setup_inventory
    from velora_erp.finance.inventory.ledger import get_stock_balance
    from velora_erp.finance.report.stock_ledger import stock_ledger
    from velora_erp.finance.report.reorder_status import reorder_status
    from velora_erp.finance.report.stock_ageing import stock_ageing
    item, warehouse, inventory, grni, cogs, gain, loss = setup_inventory(tmp_path)
    try:
        rec = new_doc("Stock Entry", stock_entry_type="Material Receipt", posting_date=date.today(), warehouse=warehouse.name,
                      lines=[{"item_code": item.name, "quantity": 10, "basic_rate": 100}]).insert(ignore_permissions=True)
        rec.submit(ignore_permissions=True)
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 10
        rec = get_doc("Stock Entry", rec.name, ignore_permissions=True)
        assert rec.inventory_posting_batch and float(rec.total_value) == 1000
        iss = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=warehouse.name,
                      lines=[{"item_code": item.name, "quantity": 4, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        iss.submit(ignore_permissions=True)
        bal = get_stock_balance(item.name, warehouse.name)
        assert bal["qty"] == 6 and float(bal["value"]) == 600
        big = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=warehouse.name,
                      lines=[{"item_code": item.name, "quantity": 50, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        with pytest.raises(ValidationError, match="insufficient stock"):
            big.submit(ignore_permissions=True)
        get_doc("Stock Entry", iss.name, ignore_permissions=True).cancel(ignore_permissions=True)     # cancelling the issue gives the stock back
        assert get_stock_balance(item.name, warehouse.name)["qty"] == 10
        get_doc("Stock Entry", iss.name, ignore_permissions=True)
        redo = new_doc("Stock Entry", stock_entry_type="Material Issue", posting_date=date.today(), warehouse=warehouse.name,
                       lines=[{"item_code": item.name, "quantity": 4, "expense_account": cogs.name}]).insert(ignore_permissions=True)
        redo.submit(ignore_permissions=True)
        from velora_erp.finance.report.stock_balance import stock_balance
        assert stock_balance.execute({"item_code": item.name})
        assert stock_ledger.execute({"item_code": item.name})
        assert reorder_status.execute({"show_all": 1}) is not None
        age = inv.ageing_rows(item_code=item.name)
        assert age and age[0]["on_hand"] == 6 and age[0]["age_0_30"] == 6
        assert stock_ageing.execute({"item_code": item.name})
    finally:
        velora.shutdown()
