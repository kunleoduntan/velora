from velora import get_list
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.requests import reorder_rows


def execute(filters):
    check_access()
    f = filters or {}
    rb = ReportBuilder("Reorder Status", [Column("item_code", "Item", "Link"), Column("item_name", "Name"), Column("item_group", "Group"),
        Column("on_hand", "On Hand", "Float"), Column("reorder_level", "Reorder Level", "Float"), Column("on_order", "On Order", "Float"), Column("requested", "Requested", "Float"),
        Column("to_order", "Suggested Order", "Float"), Column("preferred_supplier", "Supplier"), Column("status", "Status")])
    for r in reorder_rows(item_group=f.get("item_group") or None, show_all=bool(f.get("show_all"))):
        rb.row(r)
    return rb
