from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.procurement import comparison_rows


def execute(filters):
    check_access()
    rfq = (filters or {}).get("request_for_quotation")
    if not rfq:
        throw("Choose the Request for Quotation to compare.")
    rb = ReportBuilder("Quotation Comparison", [Column("item_code", "Item", "Link"), Column("rank", "Rank", "Int"), Column("supplier", "Supplier", "Link"), Column("quotation", "Quotation", "Link"),
        Column("status", "Status"), Column("currency", "Currency"), Column("requested_quantity", "Asked", "Float"), Column("quoted_quantity", "Quoted", "Float"),
        Column("rate", "Rate", "Currency"), Column("rate_base", "Rate (Base)", "Currency"), Column("amount", "Amount", "Currency"), Column("lead_time_days", "Lead Days", "Int"), Column("valid_till", "Valid Till", "Date")])
    for r in comparison_rows(rfq):
        rb.row(r)
    return rb
