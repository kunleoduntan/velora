from decimal import Decimal
from velora import throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access
from velora_erp.finance.inventory.ledger import get_stock_balances


def execute(filters):
    check_access()
    rows = get_stock_balances(
        item_code=filters.get("item_code") or None,
        warehouse=filters.get("warehouse") or None,
        batch=filters.get("batch") or None,
        serial_number=filters.get("serial_number") or None,
    )
    rows = [r for r in rows if r["qty"] != 0 or r["stock_value"] != 0]
    if len(rows) > 5000:
        throw("More than 5,000 stock balance rows were found. Select an Item or Warehouse to narrow the report.")
    rb = ReportBuilder("Stock Balance", [
        Column("item_code", "Item", "Link"),
        Column("warehouse", "Warehouse", "Link"),
        Column("batch", "Batch", "Link"),
        Column("serial_number", "Serial Number", "Link"),
        Column("qty", "On Hand Quantity", "Float"),
        Column("valuation_rate", "Valuation Rate", "Currency"),
        Column("stock_value", "Stock Value", "Currency"),
    ])
    for row in rows:
        rb.row({
            "item_code": row["item_code"], "warehouse": row["warehouse"],
            "batch": row["batch"] or "", "serial_number": row["serial_number"] or "",
            "qty": row["qty"], "valuation_rate": row["valuation_rate"], "stock_value": row["stock_value"],
        })
    return rb
