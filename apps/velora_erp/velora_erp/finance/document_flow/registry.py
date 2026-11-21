"""Declarative, discoverable document-flow definitions for VeloraERP.

A flow definition describes an available business transition. Only flows with
implemented target doctypes and reviewed conversion handlers are executable.
The catalogue can therefore expose planned transitions without pretending they
are operational.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class DocumentFlow:
    source_doctype: str
    target_doctype: str
    label: str
    status: str = "planned"  # active | planned | disabled
    handler: str | None = None
    cardinality: str = "one_to_one"  # one_to_one | one_to_many
    description: str = ""
    # When may the button appear? stage: "submitted" (the default), "draft" (before it is submitted) or "open" (documents that are
    # not submitted at all, such as a request). `ready` narrows it further: {field: [allowed values]} on the source document.
    stage: str = "submitted"
    ready: tuple = ()


# Keep the registry explicit and auditable. A flow is not executable merely
# because a target DocType name appears here.
DOCUMENT_FLOWS: tuple[DocumentFlow, ...] = (
    DocumentFlow("Sales Invoice", "Receipt", "Receive Payment", "active", "invoice_receipt", "one_to_many", "Receive full or partial payment against a sales invoice; the outstanding balance is proposed."),
    DocumentFlow("Purchase Invoice", "Payment", "Pay", "active", "invoice_payment", "one_to_many", "Pay full or partial settlement against a purchase invoice; the outstanding balance is proposed."),
    DocumentFlow("Sales Invoice", "Sales Return", "Create Sales Return", "active", "sales_return", "one_to_many", "Return goods and reverse the related customer invoice value."),
    DocumentFlow("Sales Invoice", "Delivery Note", "Create Delivery Note", description="Create a delivery instruction from invoice lines; stock movement rules apply."),
    DocumentFlow("Sales Invoice", "Waybill", "Create Waybill", description="Prepare transport documentation from invoice and delivery details."),
    DocumentFlow("Purchase Invoice", "Purchase Return", "Create Purchase Return", "active", "purchase_return", "one_to_many", "Return goods and reverse the related supplier invoice value."),
    DocumentFlow("Purchase Invoice", "Purchase Receipt", "Create Purchase Receipt", description="Record receipt of goods against the purchasing transaction."),
    DocumentFlow("Sales Quotation", "Sales Order", "Create Sales Order", "active", "quotation_order", "one_to_many", "Convert approved quotation quantities into one or more customer orders."),
    DocumentFlow("Sales Order", "Delivery Note", "Create Delivery Note", "active", "sales_order_delivery", "one_to_many", "Fulfil ordered quantities, including partial deliveries."),
    DocumentFlow("Sales Order", "Sales Invoice", "Create Sales Invoice", "active", "sales_order_invoice", "one_to_many", "Invoice remaining Sales Order quantities in one or more partial invoices."),
    DocumentFlow("Sales Quotation", "Sales Invoice", "Create Sales Invoice", "active", "quotation_invoice", "one_to_many", "Invoice an approved quotation directly; stock items are issued by the invoice."),
    DocumentFlow("Delivery Note", "Sales Invoice", "Create Sales Invoice", "active", "delivery_invoice", "one_to_many", "Bill the quantities of this delivery."),
    DocumentFlow("Waybill", "Sales Invoice", "Create Sales Invoice", "active", "waybill_invoice", "one_to_many", "Bill the delivery this waybill transports."),
    DocumentFlow("Delivery Note", "Waybill", "Create Waybill", "active", "delivery_waybill", "one_to_one", "Prepare transport documentation for a submitted delivery."),
    DocumentFlow("Purchase Order", "Purchase Receipt", "Create Purchase Receipt", "active", "purchase_order_receipt", "one_to_many", "Receive ordered quantities, including partial receipts."),
    DocumentFlow("Purchase Order", "Purchase Invoice", "Create Purchase Invoice", "active", "purchase_order_invoice", "one_to_many", "Invoice a purchase order directly (the receipt is optional); stock not yet received is received by the invoice."),
    DocumentFlow("Sales Order", "Receipt", "Receive Advance", "active", "order_advance_receipt", "one_to_many", "Receive a customer advance against a Sales Order; the amount sits on the customer's advance account until applied to an invoice."),
    DocumentFlow("Purchase Order", "Payment", "Pay Advance", "active", "order_advance_payment", "one_to_many", "Pay a supplier advance against a Purchase Order; the amount sits on the supplier's advance account until applied to an invoice."),
    DocumentFlow("Material Request", "Purchase Order", "Create Purchase Order", "active", "request_order", "one_to_many", "Order the outstanding quantities of an approved purchase request from a supplier.", "open", (("request_type", ("Purchase",)), ("request_status", ("Approved",)))),
    DocumentFlow("Material Request", "Stock Transfer", "Create Stock Transfer", "active", "request_transfer", "one_to_many", "Move the requested stock between warehouses.", "open", (("request_type", ("Material Transfer",)), ("request_status", ("Approved",)))),
    DocumentFlow("Material Request", "Stock Entry", "Create Stock Issue", "active", "request_issue", "one_to_many", "Issue the requested stock for internal use.", "open", (("request_type", ("Material Issue",)), ("request_status", ("Approved",)))),
    DocumentFlow("Material Request", "Request for Quotation", "Request Quotations", "active", "request_rfq", "one_to_many", "Ask suppliers to quote for the outstanding quantities of an approved purchase request.", "open", (("request_type", ("Purchase",)), ("request_status", ("Approved",)))),
    DocumentFlow("Request for Quotation", "Supplier Quotation", "Record Supplier Quotation", "active", "rfq_quotation", "one_to_many", "Enter the prices one supplier quoted against this request.", "open", (("status", ("Sent", "Quotations Received")),)),
    DocumentFlow("Supplier Quotation", "Purchase Order", "Create Purchase Order", "active", "quotation_purchase_order", "one_to_one", "Order from this quotation. It is marked Awarded and the other quotations for the same request are marked Lost.", "open", (("status", ("Received",)),)),
    DocumentFlow("Stock Transfer", "Stock Transfer Receipt", "Receive Goods", "active", "transfer_receipt", "one_to_many", "Receive stock that is in transit into its destination warehouse (all of it, or part now and the rest later).", "submitted", (("transit_status", ("In Transit", "Partially Received")),)),
    DocumentFlow("Purchase Receipt", "Quality Inspection", "Inspect Goods", "active", "receipt_inspection", "one_to_many", "Create the quality inspections the received items require.", "draft"),
    DocumentFlow("Delivery Note", "Quality Inspection", "Inspect Goods", "active", "delivery_inspection", "one_to_many", "Create the quality inspections the delivered items require.", "draft"),
    DocumentFlow("Purchase Receipt", "Purchase Invoice", "Create Purchase Invoice", "active", "purchase_receipt_invoice", "one_to_many", "Match supplier invoice quantities and values against received goods and clear GRNI."),
)


def is_eligible(flow: DocumentFlow, doc) -> bool:
    """May this flow be offered for this particular document right now?"""
    get = doc.get if isinstance(doc, dict) else (lambda k, d=None: getattr(doc, k, d))
    docstatus = int(get("docstatus", 0) or 0)
    if flow.stage == "submitted" and docstatus != 1:
        return False
    if flow.stage == "draft" and docstatus != 0:
        return False
    return all(str(get(field) or "") in values for field, values in flow.ready)


def get_document_flows(source_doctype: str, *, include_planned: bool = False, doc=None) -> list[dict]:
    """Return flow actions suitable for a document's Create From menu (narrowed to the document when one is given)."""
    result = []
    for flow in DOCUMENT_FLOWS:
        if flow.source_doctype != source_doctype:
            continue
        if not include_planned and flow.status != "active":
            continue
        if doc is not None and not is_eligible(flow, doc):
            continue
        result.append({
            "source_doctype": flow.source_doctype,
            "target_doctype": flow.target_doctype,
            "label": flow.label,
            "status": flow.status,
            "available": flow.status == "active" and bool(flow.handler),
            "cardinality": flow.cardinality,
            "description": flow.description,
        })
    return result


def get_flow(source_doctype: str, target_doctype: str) -> DocumentFlow | None:
    return next((f for f in DOCUMENT_FLOWS if f.source_doctype == source_doctype and f.target_doctype == target_doctype), None)
