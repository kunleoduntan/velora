from velora import get_list, throw
from velora.reporting import Column, ReportBuilder
from velora_erp.finance.reporting_provider import check_access


def execute(filters):
    check_access()
    f = filters or {}
    flt = []
    for k in ("item_code", "warehouse", "voucher_type"):
        if f.get(k): flt.append([k, "=", f[k]])
    if f.get("from_date"): flt.append(["posting_date", ">=", str(f["from_date"])[:10]])
    if f.get("to_date"): flt.append(["posting_date", "<=", str(f["to_date"])[:10]])
    rows = get_list("Stock Ledger Record", filters=flt, fields=["posting_date", "item_code", "warehouse", "actual_qty", "qty_after_transaction", "valuation_rate",
                    "stock_value_difference", "stock_value_after_transaction", "voucher_type", "voucher_no", "batch", "serial_number", "creation"], limit=5001, ignore_permissions=True)
    if len(rows) > 5000: throw("More than 5,000 movements match. Narrow the report by item, warehouse or dates.")
    rb = ReportBuilder("Stock Ledger", [Column("posting_date", "Date", "Date"), Column("item_code", "Item", "Link"), Column("warehouse", "Warehouse", "Link"),
        Column("in_qty", "In", "Float"), Column("out_qty", "Out", "Float"), Column("balance_qty", "Balance Qty", "Float"), Column("valuation_rate", "Valuation Rate", "Currency"),
        Column("value_change", "Value Change", "Currency"), Column("balance_value", "Balance Value", "Currency"), Column("voucher_type", "Voucher Type"), Column("voucher_no", "Voucher"), Column("batch", "Batch"), Column("serial_number", "Serial")])
    for r in sorted(rows, key=lambda r: (str(r["posting_date"]), str(r.get("creation") or ""))):
        q = float(r["actual_qty"] or 0)
        rb.row({"posting_date": r["posting_date"], "item_code": r["item_code"], "warehouse": r["warehouse"], "in_qty": q if q > 0 else 0, "out_qty": -q if q < 0 else 0,
                "balance_qty": r["qty_after_transaction"], "valuation_rate": r["valuation_rate"], "value_change": r["stock_value_difference"], "balance_value": r["stock_value_after_transaction"],
                "voucher_type": r["voucher_type"], "voucher_no": r["voucher_no"], "batch": r.get("batch") or "", "serial_number": r.get("serial_number") or ""})
    rb.total("TOTAL")
    return rb
