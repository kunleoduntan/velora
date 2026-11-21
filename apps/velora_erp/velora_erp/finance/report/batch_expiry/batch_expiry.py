from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.expiry import batch_rows


def execute(filters):
    check_access()
    f = filters or {}
    days = f.get("days")
    rb = ReportBuilder("Batch Expiry", [Column("item_code", "Item", "Link"), Column("batch", "Batch", "Link"), Column("warehouse", "Warehouse", "Link"),
        Column("quantity", "Quantity", "Float"), Column("stock_value", "Stock Value", "Currency"), Column("expiry_date", "Expiry Date", "Date"),
        Column("days_left", "Days Left", "Int"), Column("status", "Status")])
    for r in batch_rows(int(days) if days not in (None, "") else None, f.get("warehouse") or None, f.get("item_code") or None, include_ok=bool(f.get("include_ok"))):
        rb.row(r)
    return rb
