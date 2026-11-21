from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.reservations import availability_rows


def execute(filters):
    check_access()
    f = filters or {}
    rb = ReportBuilder("Stock Availability", [Column("item_code", "Item", "Link"), Column("warehouse", "Warehouse", "Link"), Column("on_hand", "On Hand", "Float"),
        Column("reserved", "Reserved", "Float"), Column("available", "Available", "Float")])
    for r in availability_rows(f.get("warehouse") or None, f.get("item_code") or None):
        rb.row(r)
    return rb
