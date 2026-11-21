from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.requests import ageing_rows


def execute(filters):
    check_access()
    f = filters or {}
    rb = ReportBuilder("Stock Ageing", [Column("item_code", "Item", "Link"), Column("warehouse", "Warehouse", "Link"),
        Column("on_hand", "On Hand", "Float"), Column("age_0_30", "0-30 days", "Float"), Column("age_31_60", "31-60", "Float"), Column("age_61_90", "61-90", "Float"),
        Column("age_over_90", "Over 90", "Float"), Column("oldest_days", "Oldest (days)", "Int"), Column("stock_value", "Stock Value", "Currency")])
    for r in ageing_rows(warehouse=f.get("warehouse") or None, item_code=f.get("item_code") or None, as_of=f.get("as_of")):
        rb.row(r)
    rb.total("TOTAL")
    return rb
