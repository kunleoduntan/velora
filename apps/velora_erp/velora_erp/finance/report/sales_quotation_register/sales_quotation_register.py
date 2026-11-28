from datetime import date
from velora import get_doc, get_list, throw
from velora.reporting import Column, ReportBuilder
from velora.permissions import check_permission
from velora.meta.registry import registry


def execute(filters):
    filters = filters or {}
    start, end = str(filters.get("from_date") or ""), str(filters.get("to_date") or "")
    if not start or not end:
        throw("From Date and To Date are required for Sales Quotation Register.")
    if start > end:
        throw("From Date cannot be later than To Date.")
    check_permission(registry.get("Sales Quotation"), "read")
    docs = get_list("Sales Quotation", filters={"docstatus": 1},
                    fields=["name", "document_date", "valid_until", "party", "currency", "total_amount", "document_status", "approval_status"],
                    limit=5001, ignore_permissions=True)
    if len(docs) > 5000:
        throw("More than 5,000 submitted quotations were found. Narrow the date range.")
    docs = [d for d in docs if start <= str(d.get("document_date") or "")[:10] <= end
            and (not filters.get("customer") or d.get("party") == filters["customer"])]
    rb = ReportBuilder("Sales Quotation Register", [
        Column("quotation", "Quotation", "Link"),
        Column("quotation_date", "Quotation Date", "Date"),
        Column("valid_until", "Valid Until", "Date"),
        Column("customer", "Customer", "Link"),
        Column("currency", "Currency", "Data"),
        Column("quotation_value", "Quotation Value", "Currency"),
        Column("approval_status", "Approval", "Data"),
        Column("document_status", "Status", "Data"),
        Column("ordered_quantity", "Ordered Quantity", "Float", total="sum"),
        Column("quoted_quantity", "Quoted Quantity", "Float", total="sum"),
        Column("conversion_percent", "Quantity Converted (%)", "Percent", total="none"),
    ])
    for summary in docs:
        quote = get_doc("Sales Quotation", summary["name"], ignore_permissions=True)
        quoted = sum(float(getattr(line, "quantity", 0) or 0) for line in quote.lines or [])
        ordered = 0.0
        orders = get_list("Sales Order", filters={"source_doctype": "Sales Quotation", "source_document": quote.name}, fields=["name", "docstatus"], limit=1000, ignore_permissions=True)
        for order_row in orders:
            if int(order_row.get("docstatus") or 0) == 2:
                continue
            order = get_doc("Sales Order", order_row["name"], ignore_permissions=True)
            ordered += sum(float(getattr(line, "quantity", 0) or 0) for line in order.lines or [])
        effective_status = quote.document_status or "Open"
        if quoted and ordered >= quoted:
            effective_status = "Ordered"
        elif ordered > 0:
            effective_status = "Partially Ordered"
        elif str(quote.valid_until or "") < date.today().isoformat():
            effective_status = "Expired"
        if filters.get("document_status") and effective_status != filters["document_status"]:
            continue
        rb.row({
            "quotation": quote.name, "quotation_date": quote.document_date,
            "valid_until": quote.valid_until, "customer": quote.party,
            "currency": quote.currency, "quotation_value": quote.total_amount or 0,
            "approval_status": quote.approval_status, "document_status": effective_status,
            "ordered_quantity": ordered, "quoted_quantity": quoted,
            "conversion_percent": round(ordered / quoted * 100, 2) if quoted else None,
        })
    rb.total("TOTAL")
    return rb.build(filters=[("From Date", start), ("To Date", end),
                             ("Customer", filters.get("customer") or "All"),
                             ("Status", filters.get("document_status") or "All")],
                    notes=["Quotation value is in the quotation transaction currency.",
                           "Quantity conversion is aggregated across draft and submitted Sales Orders created from each quotation. Status is derived in this report: Ordered, Partially Ordered, Expired or the stored quotation status.",
                           "Expired quotations are not automatically converted; validity must be extended and independently approved first."])
