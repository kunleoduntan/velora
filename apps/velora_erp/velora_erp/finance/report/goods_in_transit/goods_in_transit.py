from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.transit import transit_rows


def execute(filters):
    check_access()
    rb = ReportBuilder("Goods in Transit", [Column("transfer", "Stock Transfer", "Link"), Column("posting_date", "Sent On", "Date"), Column("source_warehouse", "From"),
        Column("target_warehouse", "To"), Column("item_code", "Item", "Link"), Column("batch", "Batch"), Column("sent", "Sent", "Float"),
        Column("received", "Received", "Float"), Column("in_transit", "Still In Transit", "Float"), Column("days_in_transit", "Days", "Int"), Column("status", "Status")])
    for r in transit_rows((filters or {}).get("warehouse") or None):
        rb.row(r)
    return rb
