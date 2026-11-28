"""Create follow-on documents without re-keying source transaction data.

Conversion creates a new draft document. It never submits or posts the target,
never mutates the source and always retains an explicit source-document link.
"""
from __future__ import annotations
from velora_erp.finance.multicurrency import base_currency

from copy import deepcopy
from decimal import Decimal

from velora import db, get_doc, get_list, new_doc, throw
from .registry import get_flow


# Deliberately explicit: only reviewed business flows are exposed here.
# Target-specific mandatory fields (e.g. bank/cash account) remain for user entry.
FLOW_MAP = {
    ("Sales Invoice", "Receipt"): {
        "party_type": "Customer", "purpose": "Customer Receipt", "table": "lines",
        "source_amount": "grand_total", "date_field": "receipt_date", "child_type": "Receipt Line",
        "side": "Credit", "account_source": "party_control", "description": "Receipt against Sales Invoice {name}",
    },
    ("Purchase Invoice", "Payment"): {
        "party_type": "Supplier", "purpose": "Supplier Payment", "table": "lines",
        "source_amount": "grand_total", "date_field": "payment_date", "child_type": "Payment Line",
        "side": "Debit", "account_source": "party_control", "description": "Payment against Purchase Invoice {name}",
    },
    ("Sales Order", "Receipt"): {
        "party_type": "Customer", "purpose": "Customer Advance", "table": "lines",
        "source_amount": "grand_total", "date_field": "receipt_date", "source_date": "document_date", "child_type": "Receipt Line",
        "side": "Credit", "account_source": "party_advance", "description": "Advance against Sales Order {name}",
    },
    ("Purchase Order", "Payment"): {
        "party_type": "Supplier", "purpose": "Supplier Advance", "table": "lines",
        "source_amount": "grand_total", "date_field": "payment_date", "source_date": "document_date", "child_type": "Payment Line",
        "side": "Debit", "account_source": "party_advance", "description": "Advance against Purchase Order {name}",
    },
}


def _value(doc, field, default=None):
    value = getattr(doc, field, default)
    return default if value is None else value


def _existing_target(source_type, source_name, target_type):
    rows = get_list(target_type, filters={"source_doctype": source_type, "source_document": source_name}, fields=["name"], limit=2)
    if rows:
        throw(f"A {target_type} has already been created from {source_type} {source_name}: {rows[0]['name']}. Open that document instead of creating a duplicate.")


def _create_financial_document(source_doctype: str, source_name: str, target_doctype: str, overrides: dict | None = None):
    """Insert a draft target from a submitted source using a reviewed flow map.

    Returns the inserted target document. Overrides are restricted to fields
    that users are expected to complete/change after conversion.
    """
    key = (source_doctype, target_doctype)
    flow = get_flow(source_doctype, target_doctype)
    config = FLOW_MAP.get(key) if flow and flow.status == "active" and flow.handler else None
    if not config:
        throw(f"Create From {source_doctype} to {target_doctype} is not implemented or enabled. Check the document-flow catalogue.")
    source = get_doc(source_doctype, source_name)
    if int(_value(source, "docstatus", 0) or 0) != 1:
        throw("Create From is available only for submitted source documents.")
    if source_doctype == "Sales Quotation":
        from datetime import date
        if _value(source, "approval_status") != "Approved":
            throw("Only approved Sales Quotations can be converted to Sales Orders.")
        if str(_value(source, "valid_until") or "") < date.today().isoformat():
            throw("This Sales Quotation has expired and cannot be converted. Create and approve a revised quotation.")
    if flow.cardinality == "one_to_one":
        _existing_target(source_doctype, source_name, target_doctype)
    if source_doctype in ("Sales Order", "Purchase Order") and _value(source, "document_status") == "Closed":
        throw(f"{source_doctype} {source_name} is closed.")

    party_type = config["party_type"]
    party = _value(source, "party")
    if not party:
        throw("The source document has no customer or supplier.")
    party_master = get_doc(party_type, party, ignore_permissions=True)
    advance = config.get("account_source") == "party_advance"
    control_account = _value(party_master, "advance_account" if advance else "control_account")
    if not control_account:
        throw(f"Configure the {party_type} {'advance' if advance else 'control'} account before creating the follow-on document.")

    source_amount = Decimal(str(_value(source, config["source_amount"], 0) or 0))
    if not source_amount.is_finite() or source_amount <= 0:
        throw("The source document total must be greater than zero.")
    # What is still to be settled: the total less what is already settled and less drafts already raised from this document.
    settled = Decimal(str(_value(source, "amount_settled", 0) or 0))
    pending = Decimal("0")
    for draft in get_list(target_doctype, filters={"source_doctype": source_doctype, "source_document": source_name}, fields=["name", "docstatus"], limit=500, ignore_permissions=True):
        if int(draft.get("docstatus") or 0) == 0:
            pending += sum((Decimal(str(getattr(l, "amount", 0) or 0)) for l in get_doc(target_doctype, draft["name"], ignore_permissions=True).lines or []), Decimal("0"))
        elif advance and int(draft.get("docstatus") or 0) == 1:
            settled += sum((Decimal(str(getattr(l, "amount", 0) or 0)) for l in get_doc(target_doctype, draft["name"], ignore_permissions=True).lines or []), Decimal("0"))
    outstanding = source_amount - settled - pending
    if outstanding <= 0:
        throw(f"{source_doctype} {source_name} has nothing left to {'advance' if advance else 'settle'} (settled or already covered by a draft {target_doctype}).")
    source_amount = outstanding
    requested_amount = (overrides or {}).get("settlement_amount")
    amount = Decimal(str(requested_amount)) if requested_amount not in (None, "") else source_amount
    if not amount.is_finite() or amount <= 0 or amount > source_amount:
        throw("Settlement Amount must be greater than zero and cannot exceed the source invoice total. Outstanding-balance enforcement will be applied by the invoice allocation service.")

    payload = {
        "source_doctype": source_doctype,
        "source_document": source_name,
        "purpose": config["purpose"],
        "currency": _value(source, "currency"),
        "exchange_rate": _value(source, "exchange_rate", 1),
        "external_reference": source_name,
        "narration": config["description"].format(name=source_name),
        config["date_field"]: _value(source, config.get("source_date", "posting_date")),
        "lines": [{
            "account": control_account,
            "entry_side": config["side"],
            "amount": amount,
            "party_type": party_type,
            "party": party,
            "description": config["description"].format(name=source_name),
            "settlement_reference": source_name,
            "invoice_reference": source_name,
            "allocation_amount": amount,
        }],
    }
    if advance:
        for key in ("settlement_reference", "invoice_reference", "allocation_amount"):
            payload["lines"][0].pop(key, None)
    if not ((overrides or {}).get("cash_account") or (overrides or {}).get("bank_account")):
        throw("Select the Bank Account when creating a Receipt or Payment from an invoice.")
    if overrides:
        allowed = {"settlement_amount", "cash_account", "bank_account", "payment_method", "instrument_reference", "received_from", "value_date", "receipt_date", "payment_date", "posting_date", "narration"}
        invalid = set(overrides) - allowed
        if invalid:
            throw("Unsupported Create From override(s): " + ", ".join(sorted(invalid)))
        payload.update({k: deepcopy(v) for k, v in overrides.items() if k != "settlement_amount"})

    target = new_doc(target_doctype, **payload)
    target.insert()
    return target


OPERATIONAL_FLOW_MAP = {
    ("Sales Quotation", "Sales Order"): {"target_table": "Sales Order Line", "source_table": "Sales Quotation Line", "date_field": "document_date", "cardinality": "one_to_many"},
    ("Sales Order", "Delivery Note"): {"target_table": "Delivery Note Line", "source_table": "Sales Order Line", "date_field": "document_date", "cardinality": "one_to_many"},
    ("Purchase Order", "Purchase Receipt"): {"target_table": "Purchase Receipt Line", "source_table": "Purchase Order Line", "date_field": "document_date", "cardinality": "one_to_many"},
    ("Delivery Note", "Waybill"): {"target_table": "Waybill Line", "source_table": "Delivery Note Line", "date_field": "document_date", "cardinality": "one_to_one"},
    ("Sales Invoice", "Waybill"): {"target_table": "Waybill Line", "source_table": "Sales Invoice Line", "date_field": "document_date", "cardinality": "one_to_many"},
    ("Sales Order", "Waybill"): {"target_table": "Waybill Line", "source_table": "Sales Order Line", "date_field": "document_date", "cardinality": "one_to_many"},
}


def _source_line_key(line):
    return str(getattr(line, "name", "") or "")


def _converted_quantities(source_doctype, source_name, target_doctype):
    """Sum active draft/submitted follow-on quantities by immutable source line id (header or per-line source)."""
    from velora_erp.finance.fulfilment import line_totals
    return line_totals(target_doctype, source_doctype, source_name)


def _create_operational_document_locked(source_doctype, source_name, target_doctype, overrides=None):
    config = OPERATIONAL_FLOW_MAP[(source_doctype, target_doctype)]
    flow = get_flow(source_doctype, target_doctype)
    source = get_doc(source_doctype, source_name)
    source._lock_and_check()  # serialize partial-quantity reservations against the same source document
    if int(_value(source, "docstatus", 0) or 0) != 1:
        throw("Create From is available only for submitted source documents.")
    if source_doctype == "Sales Quotation":
        from datetime import date
        if _value(source, "approval_status") != "Approved":
            throw("Only approved Sales Quotations can be converted to Sales Orders.")
        if str(_value(source, "valid_until") or "") < date.today().isoformat():
            throw("This Sales Quotation has expired and cannot be converted. Create and approve a revised quotation.")
    if flow.cardinality == "one_to_one":
        _existing_target(source_doctype, source_name, target_doctype)
    overrides = overrides or {}
    allowed = {"document_date", "delivery_address", "dispatch_reference", "warehouse", "transporter", "vehicle_number", "driver_name", "driver_phone", "dispatch_date", "destination", "quantities"}
    invalid = set(overrides) - allowed
    if invalid:
        throw("Unsupported Create From override(s): " + ", ".join(sorted(invalid)))
    totals = _converted_quantities(source_doctype, source_name, target_doctype) if flow.cardinality == "one_to_many" else {}
    requested = overrides.get("quantities") or {}
    target_lines = []
    for source_line in source.lines or []:
        if target_doctype == "Waybill" and not _value(source_line, "item_code"):
            continue                                   # a waybill moves goods: service and charge lines are left out
        line_key = _source_line_key(source_line)
        source_qty = Decimal(str(_value(source_line, "quantity", 0) or 0))
        if source_qty <= 0:
            throw("Every source line must have a positive quantity before it can be converted.")
        already = totals.get(line_key, Decimal("0"))
        remaining = source_qty - already
        if flow.cardinality == "one_to_many":
            raw_qty = requested.get(line_key, remaining)
            qty = Decimal(str(raw_qty))
            if not qty.is_finite() or qty <= 0 or qty > remaining:
                throw(f"Line {line_key}: requested quantity must be greater than zero and cannot exceed the remaining quantity {remaining}.")
        else:
            qty = source_qty
        target_line = {
            "source_line": line_key,
            "item_code": _value(source_line, "item_code"),
            "description": _value(source_line, "description"),
            "quantity": qty,
            "uom": _value(source_line, "uom"),
            "conversion_factor": _value(source_line, "conversion_factor", 1),
            "valuation_rate": _value(source_line, "rate", _value(source_line, "valuation_rate", 0)),
            "batch": _value(source_line, "batch"),
            "serial_number": _value(source_line, "serial_number"),
        }
        if target_doctype in ("Delivery Note", "Sales Order"):
            target_line.update({
                "rate": _value(source_line, "rate", 0),
                "discount_percentage": _value(source_line, "discount_percentage", 0),
                "discount_amount": _value(source_line, "discount_amount", 0),
                "price_basis": _value(source_line, "price_basis", "Automatic"),
                "cost_rate": _value(source_line, "cost_rate"),
                "cost_source": _value(source_line, "cost_source"),
                "price_note": _value(source_line, "price_note"),
            })
        target_lines.append(target_line)
    if not target_lines:
        throw("The source document has no goods lines to convert." if target_doctype == "Waybill" else "The source document has no lines to convert.")
    payload = {
        "party": _value(source, "party"),
        "source_doctype": source_doctype,
        "source_document": source_name,
        "document_date": overrides.get("document_date") or _value(source, "document_date"),
        "currency": _value(source, "currency", None) or base_currency(),
        "exchange_rate": _value(source, "exchange_rate", 1),
        "lines": target_lines,
        "narration": f"Created from {source_doctype} {source_name}",
    }
    if target_doctype == "Waybill" and source_doctype == "Delivery Note":
        payload["delivery_note"] = source_name
    for key, value in overrides.items():
        if key != "quantities":
            payload[key] = deepcopy(value)
    target = new_doc(target_doctype, **payload)
    target.insert()
    return target


def _create_operational_document(source_doctype, source_name, target_doctype, overrides=None):
    # The source row lock, quantity aggregation and target insert share one DB
    # transaction. Concurrent requests for the same order cannot reserve the
    # same remaining quantity twice on row-locking databases.
    with db.transaction():
        return _create_operational_document_locked(source_doctype, source_name, target_doctype, overrides)


def _create_sales_flow(source_doctype, source_name, target_doctype, overrides=None):
    from . import more_flows
    extra = {("Delivery Note", "Sales Invoice"): more_flows.create_sales_invoice_from_delivery, ("Waybill", "Sales Invoice"): more_flows.create_sales_invoice_from_waybill,
             ("Sales Quotation", "Sales Invoice"): more_flows.create_sales_invoice_from_quotation, ("Purchase Order", "Purchase Invoice"): more_flows.create_purchase_invoice_from_order}
    if (source_doctype, target_doctype) in extra:
        return extra[(source_doctype, target_doctype)](source_name, dict(overrides or {}))
    from .sales_invoicing import create_sales_invoice_from_order
    payload = overrides or {}
    quantities = payload.pop("quantities", {}) if isinstance(payload, dict) else {}
    return create_sales_invoice_from_order(source_name, quantities=quantities, overrides=payload)


# Invoice-linked return conversion. Returns are one-to-many and each line
# carries the original invoice line id; financial return values are capped by
# cumulative prior returns in the validation layer.
RETURN_FLOW_MAP = {
    ("Sales Invoice", "Sales Return"): ("Sales Return", "Sales Return Line"),
    ("Purchase Invoice", "Purchase Return"): ("Purchase Return", "Purchase Return Line"),
}

def _create_return_from_invoice(source_doctype, source_name, target_doctype, overrides=None):
    from velora import new_doc
    with db.transaction():
        source = get_doc(source_doctype, source_name)
        source._lock_and_check()
        if int(_value(source, "docstatus", 0) or 0) != 1:
            throw("Create From is available only for submitted source invoices.")
        target_type, _child_type = RETURN_FLOW_MAP[(source_doctype, target_doctype)]
        existing = get_list(target_type, filters={"source_invoice": source_name}, fields=["name", "docstatus"], limit=1000, ignore_permissions=True)
        returned = {}
        returned_tax = {}
        for item in existing:
            if int(item.get("docstatus") or 0) == 2:
                continue
            prior = get_doc(target_type, item["name"])
            for line in prior.lines or []:
                key = str(_value(line, "source_line", ""))
                returned[key] = returned.get(key, Decimal("0")) + Decimal(str(_value(line, "amount", 0) or 0))
                returned_tax[key] = returned_tax.get(key, Decimal("0")) + Decimal(str(_value(line, "tax_amount", 0) or 0))
        overrides = overrides or {}
        requested_quantities = overrides.get("quantities") or {}
        lines = []
        for line in source.lines or []:
            key = str(_value(line, "name", ""))
            remaining = Decimal(str(_value(line, "amount", 0) or 0)) - returned.get(key, Decimal("0"))
            tax_remaining = Decimal(str(_value(line, "tax_amount", 0) or 0)) - returned_tax.get(key, Decimal("0"))
            original_qty = Decimal(str(_value(line, "quantity", 0) or 0))
            already_qty = sum((Decimal(str(_value(x, "quantity", 0) or 0)) for item in existing if int(item.get("docstatus") or 0) != 2 for x in (get_doc(target_type, item["name"]).lines or []) if str(_value(x, "source_line", "")) == key), Decimal("0"))
            remaining_qty = original_qty - already_qty if original_qty > 0 else Decimal("0")
            if remaining <= 0:
                continue
            qty = Decimal(str(requested_quantities.get(key, remaining_qty if original_qty > 0 else 0)))
            if original_qty > 0:
                if qty <= 0 or qty > remaining_qty:
                    throw(f"Line {key}: requested return quantity must be positive and cannot exceed remaining quantity {remaining_qty}.")
                ratio = qty / original_qty
                line_amount = (Decimal(str(_value(line, "amount", 0))) * ratio).quantize(Decimal("0.01"))
                line_tax = (Decimal(str(_value(line, "tax_amount", 0) or 0)) * ratio).quantize(Decimal("0.01"))
                # Do not exceed the residual amount/tax after earlier returns.
                line_amount = min(line_amount, remaining)
                line_tax = min(line_tax, tax_remaining)
            else:
                line_amount, line_tax = remaining, max(Decimal("0"), tax_remaining)
            lines.append({
                "source_line": key, "item_code": _value(line, "item_code"),
                "description": _value(line, "description"), "quantity": qty,
                "uom": _value(line, "uom"), "conversion_factor": _value(line, "conversion_factor", 1), "account": _value(line, "account"),
                "amount": line_amount, "tax_account": _value(line, "tax_account"),
                "tax_code": _value(line, "tax_code"), "tax_rate": _value(line, "tax_rate", 0),
                "tax_amount": line_tax, "cost_centre": _value(line, "cost_centre"),
                "batch": _value(line, "batch"), "serial_number": _value(line, "serial_number"),
                "valuation_rate": _value(line, "valuation_rate", 0),
            })
        if not lines:
            throw("All source invoice lines have already been fully returned.")
        payload = {
            "party": source.party, "source_invoice": source_name,
            "return_date": _value(source, "invoice_date"), "posting_date": _value(source, "posting_date"),
            "currency": source.currency, "exchange_rate": source.exchange_rate,
            "lines": lines, "narration": f"Return created from {source_doctype} {source_name}",
            "approval_status": "Pending",
        }
        invalid = set(overrides) - {"return_date", "posting_date", "narration", "warehouse", "quantities"}
        if invalid:
            throw("Unsupported return conversion override(s): " + ", ".join(sorted(invalid)))
        payload.update({k:v for k,v in overrides.items() if k != "quantities"})
        target = new_doc(target_type, **payload)
        target.insert()
        return target



def _create_purchase_invoice_from_receipt(source_name, overrides=None):
    """Create a supplier invoice draft from remaining un-invoiced receipt quantities."""
    from datetime import date
    from velora import get_doc, get_list, new_doc
    overrides = overrides or {}
    allowed = {"invoice_date", "posting_date", "due_date", "narration", "quantities"}
    invalid = set(overrides) - allowed
    if invalid:
        throw("Unsupported Purchase Invoice conversion override(s): " + ", ".join(sorted(invalid)))
    with db.transaction():
        receipt = get_doc("Purchase Receipt", source_name)
        receipt._lock_and_check()
        if int(_value(receipt, "docstatus", 0) or 0) != 1:
            throw("Create From is available only for submitted Purchase Receipts.")
        from velora_erp.finance.fulfilment import matched_totals
        invoiced = matched_totals(source_name)
        lines = []
        for receipt_line in receipt.lines or []:
            key = _source_line_key(receipt_line)
            received = Decimal(str(_value(receipt_line, "quantity", 0) or 0))
            remaining = received - invoiced.get(key, Decimal("0"))
            if remaining <= 0:
                continue
            requested = (overrides.get("quantities") or {}).get(key, remaining)
            qty = Decimal(str(requested))
            if not qty.is_finite() or qty <= 0 or qty > remaining:
                throw(f"Purchase Receipt line {key}: invoice quantity must be positive and cannot exceed the uninvoiced received quantity {remaining}.")
            rate = Decimal(str(_value(receipt_line, "valuation_rate", 0) or 0))
            if rate <= 0:
                throw(f"Purchase Receipt line {key} has no positive valuation rate for invoice matching.")
            lines.append({
                "item_code": _value(receipt_line, "item_code"),
                "quantity": qty,
                "uom": _value(receipt_line, "uom"),
                # The receipt's UOM conversion factor must travel with the line: GRNI is cleared in stock units, so an invoice line
                # that silently defaults to 1 clears the wrong quantity and leaves a residual on Stock Received But Not Billed.
                "conversion_factor": _value(receipt_line, "conversion_factor", 1) or 1,
                "rate": rate,
                "account": None,
                "description": _value(receipt_line, "description"),
                "amount": (qty * rate).quantize(Decimal("0.01")),
                "tax_amount": 0,
                "purchase_receipt": receipt.name,
                "purchase_receipt_line": key,
                "matched_quantity": qty,
                "batch": _value(receipt_line, "batch"),
                "serial_number": _value(receipt_line, "serial_number"),
                "valuation_rate": rate,
            })
        if not lines:
            throw("All received quantities on this Purchase Receipt have already been invoiced.")
        invoice_date = overrides.get("invoice_date") or _value(receipt, "document_date") or date.today()
        payload = {
            "party": receipt.party,
            "source_doctype": "Purchase Receipt",
            "source_document": receipt.name,
            "invoice_date": invoice_date,
            "posting_date": overrides.get("posting_date") or invoice_date,
            "due_date": overrides.get("due_date") or invoice_date,
            "currency": receipt.currency,
            "exchange_rate": receipt.exchange_rate,
            "lines": lines,
            "narration": overrides.get("narration") or f"Supplier invoice matched to Purchase Receipt {receipt.name}",
        }
        invoice = new_doc("Purchase Invoice", **payload)
        invoice.insert()
        return invoice


def _create_quality_inspections(source_doctype, source_name):
    from velora_erp.finance.inventory.quality import create_inspections
    source = get_doc(source_doctype, source_name)
    if source_doctype == "Purchase Receipt":
        return create_inspections(source, "inspection_required_on_receipt", "Incoming")
    return create_inspections(source, "inspection_required_on_delivery", "Outgoing")


def _procurement(handler):
    def run(source_doctype, source_name, target_doctype, overrides=None):
        from importlib import import_module
        module, fn = handler.rsplit(".", 1)
        return getattr(import_module(module), fn)(source_name, overrides)
    return run


# One table, read top to bottom: every reviewed (source, target) flow and the converter that builds it.
ROUTES = {
    ("Material Request", "Request for Quotation"): _procurement("velora_erp.finance.inventory.procurement.create_rfq_from_request"),
    ("Request for Quotation", "Supplier Quotation"): _procurement("velora_erp.finance.inventory.procurement.create_quotation_from_rfq"),
    ("Supplier Quotation", "Purchase Order"): _procurement("velora_erp.finance.inventory.procurement.award"),
    ("Stock Transfer", "Stock Transfer Receipt"): _procurement("velora_erp.finance.inventory.transit.create_receipt"),
    ("Purchase Receipt", "Quality Inspection"): lambda s, n, t, o=None: _create_quality_inspections(s, n),
    ("Delivery Note", "Quality Inspection"): lambda s, n, t, o=None: _create_quality_inspections(s, n),
    ("Purchase Receipt", "Purchase Invoice"): lambda s, n, t, o=None: _create_purchase_invoice_from_receipt(n, o),
    ("Purchase Invoice", "Purchase Return"): _create_return_from_invoice,
    ("Delivery Note", "Sales Invoice"): _create_sales_flow,
    ("Waybill", "Sales Invoice"): _create_sales_flow,
    ("Sales Quotation", "Sales Invoice"): _create_sales_flow,
    ("Purchase Order", "Purchase Invoice"): _create_sales_flow,
    ("Sales Order", "Sales Invoice"): _create_sales_flow,
    **{key: _create_operational_document for key in OPERATIONAL_FLOW_MAP},
}


def _sales_return(source_doctype, source_name, target_doctype, overrides=None):
    from .sales_returns import create_sales_return_from_invoice
    payload = deepcopy(overrides or {})
    quantities = payload.pop("quantities", {})
    return create_sales_return_from_invoice(source_name, quantities=quantities, overrides=payload)


ROUTES[("Sales Invoice", "Sales Return")] = _sales_return


def create_document_from(source_doctype, source_name, target_doctype, overrides=None):
    """The single entry point for Create From. A Material Request uses its own request converter; a Fixed Asset opens an
    action document pre-filled (unsaved); every other reviewed flow is in ROUTES; anything else falls to the financial flow map."""
    if source_doctype == "Fixed Asset":
        from .asset_actions import prefill
        return prefill(source_name, target_doctype)
    key = (source_doctype, target_doctype)
    if key in ROUTES:
        return ROUTES[key](source_doctype, source_name, target_doctype, overrides)
    if source_doctype == "Material Request":
        from velora_erp.finance.inventory.requests import create_from_request
        return create_from_request(source_name, target_doctype, overrides)
    return _create_financial_document(source_doctype, source_name, target_doctype, overrides)
