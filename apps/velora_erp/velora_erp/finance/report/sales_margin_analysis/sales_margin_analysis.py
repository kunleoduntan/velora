from decimal import Decimal
from velora import get_doc, get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry
from velora_erp.finance.pricing import dec, money


def execute(filters):
    filters = filters or {}
    start = str(filters.get("from_date") or "").strip()
    end = str(filters.get("to_date") or "").strip()
    if not start or not end:
        throw("From Date and To Date are required for Sales Margin Analysis.")
    if start > end:
        throw("From Date cannot be later than To Date.")

    check_permission(registry.get("Sales Invoice"), "read")
    invoices = get_list(
        "Sales Invoice", filters={"docstatus": 1},
        fields=["name", "posting_date", "party", "currency", "exchange_rate"],
        limit=5001, ignore_permissions=True,
    )
    if len(invoices) > 5000:
        throw("More than 5,000 submitted Sales Invoices were found. Narrow the date range.")
    invoices = [
        row for row in invoices
        if start <= str(row.get("posting_date") or "")[:10] <= end
        and (not filters.get("customer") or row.get("party") == filters.get("customer"))
    ]

    rb = ReportBuilder("Sales Margin Analysis", [
        Column("posting_date", "Posting Date", "Date"),
        Column("sales_invoice", "Sales Invoice", "Link"),
        Column("customer", "Customer", "Link"),
        Column("item_code", "Inventory Item", "Link"),
        Column("description", "Description", "Data"),
        Column("quantity", "Quantity", "Float"),
        Column("uom", "UOM", "Data"),
        Column("currency", "Currency", "Data"),
        Column("net_sales_base", "Net Sales (Base)", "Currency"),
        Column("cost_base", "Cost (Base)", "Currency"),
        Column("gross_profit_base", "Gross Profit (Base)", "Currency"),
        Column("gross_margin_percent", "Gross Margin (%)", "Percent", total="none"),
        Column("cost_source", "Cost Source", "Data"),
        Column("cost_status", "Cost Basis", "Data"),
    ])

    for invoice_row in invoices:
        invoice = get_doc("Sales Invoice", invoice_row["name"], ignore_permissions=True)
        fx = dec(getattr(invoice, "exchange_rate", 1) or 1, "Invoice exchange rate")
        if fx <= 0:
            throw(f"Sales Invoice {invoice.name} has an invalid exchange rate.")
        for line in invoice.lines or []:
            item_code = getattr(line, "item_code", None)
            if not item_code or (filters.get("item_code") and item_code != filters.get("item_code")):
                continue
            quantity = dec(getattr(line, "quantity", 0), "Invoiced quantity")
            if quantity <= 0:
                continue
            net_sales = dec(getattr(line, "amount", 0), "Invoice line net amount") * fx
            cost_rate = dec(getattr(line, "cost_rate", 0), "Cost rate")
            has_cost = cost_rate > 0
            cost = cost_rate * quantity * fx if has_cost else None
            cost_status = "Invoice-time estimate" if has_cost else "Missing cost snapshot"
            cost_source = getattr(line, "cost_source", "") or ""
            # Where the invoice came from a Sales Order, prefer actual Delivery Note
            # issue valuation once enough quantity has been delivered to cover this line.
            source_order = getattr(invoice, "source_document", None) if getattr(invoice, "source_doctype", None) == "Sales Order" else None
            source_line = str(getattr(line, "source_line", "") or "")
            if source_order and source_line:
                try:
                    deliveries = get_list("Delivery Note", filters={"source_doctype": "Sales Order", "source_document": source_order, "docstatus": 1}, fields=["name"], limit=5000, ignore_permissions=True)
                    delivered_stock_qty = Decimal("0")
                    delivered_cost = Decimal("0")
                    for delivery in deliveries:
                        dn = get_doc("Delivery Note", delivery["name"], ignore_permissions=True)
                        for dn_line in dn.lines or []:
                            if str(getattr(dn_line, "source_line", "") or "") != source_line:
                                continue
                            factor = dec(getattr(dn_line, "conversion_factor", 1) or 1, "Delivery conversion factor")
                            qty_stock = dec(getattr(dn_line, "quantity", 0), "Delivered quantity") * factor
                            issue_amount = dec(getattr(dn_line, "issue_cost_amount", 0), "Actual issue cost amount")
                            if qty_stock > 0 and issue_amount > 0:
                                delivered_stock_qty += qty_stock
                                delivered_cost += issue_amount
                    invoice_stock_qty = quantity * dec(getattr(line, "conversion_factor", 1) or 1, "Invoice conversion factor")
                    if delivered_stock_qty >= invoice_stock_qty and delivered_stock_qty > 0:
                        cost = (delivered_cost / delivered_stock_qty * invoice_stock_qty).quantize(Decimal("0.01"))
                        has_cost = True
                        cost_status = "Realised Delivery Note issue cost"
                        cost_source = "Stock Ledger issue valuation"
                except Exception:
                    # Reporting remains available if an optional operational cost join fails;
                    # the status clearly retains the invoice-time estimate.
                    pass
            profit = net_sales - cost if has_cost else None
            margin = (profit / net_sales * Decimal("100")) if has_cost and net_sales > 0 else None
            rb.row({
                "posting_date": invoice.posting_date,
                "sales_invoice": invoice.name,
                "customer": invoice.party,
                "item_code": item_code,
                "description": getattr(line, "description", "") or "",
                "quantity": quantity,
                "uom": getattr(line, "uom", "") or "",
                "currency": invoice.currency,
                "net_sales_base": money(net_sales),
                "cost_base": money(cost) if cost is not None else None,
                "gross_profit_base": money(profit) if profit is not None else None,
                "gross_margin_percent": margin.quantize(Decimal("0.01")) if margin is not None else None,
                "cost_source": cost_source,
                "cost_status": cost_status if has_cost else "Missing at invoice validation",
            })
    rb.total("TOTAL")
    return rb.build(
        filters=[("From Date", start), ("To Date", end),
                 ("Customer", filters.get("customer") or "All"),
                 ("Inventory Item", filters.get("item_code") or "All")],
        notes=[
            "Net Sales excludes output VAT and includes line-level discounts already reflected in the invoice amount.",
            "Where a submitted Delivery Note has issue-cost snapshots covering the invoiced quantity, the report uses realised Stock Ledger issue valuation. Otherwise it uses the invoice-time cost snapshot and labels it as an estimate.",
            "Rows without a positive cost snapshot are shown with a missing-cost status and are excluded from gross profit and gross margin totals.",
        ],
    )
