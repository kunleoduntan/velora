"""Sales and purchase invoice validation and central-engine posting."""
from __future__ import annotations
from decimal import Decimal
from velora import throw
from velora_erp.finance.validation import row
from velora_erp.finance.source_documents import decimal_amount, ensure_approved, finance_settings, persist_posting_batch_link, validate_approval_transition
from velora_erp.finance.adapters import PostingInstruction, PostingLine, post_source_document


def _account(name, expected_root, label):
    account = row("Account", name, "name", "root_type", "disabled", "account_group", "is_group")
    if not account or account["disabled"]:
        throw(f"{label}: select an active posting account.")
    group = row("Account Group", account["account_group"], "name", "disabled")
    if not group or group["disabled"]:
        throw(f"{label}: the account's classification group is missing or disabled.")
    if account["is_group"]:
        throw(f"{label}: {name} is a group account (a heading that adds up other accounts). Choose one of the accounts under it, or untick Is Group on it if it should take postings.")
    if account["root_type"] != expected_root:
        throw(f"{label} must be a {expected_root} account.")


def _validate_grni_matches(doc):
    """Validate receipt-line matching and prevent cumulative over-invoicing."""
    from velora import get_doc, get_list
    from decimal import Decimal
    from velora_erp.finance.inventory.ledger import dec
    seen = set()
    for index, line in enumerate(doc.lines or [], 1):
        receipt_name = getattr(line, "purchase_receipt", None)
        receipt_line_name = getattr(line, "purchase_receipt_line", None)
        matched_qty = dec(getattr(line, "matched_quantity", 0), f"Line {index} GRNI Matched Quantity")
        if not receipt_name:
            if receipt_line_name or matched_qty:
                throw(f"Line {index}: select a Purchase Receipt when entering a GRNI match.")
            from velora_erp.finance.inventory.ledger import is_stock_item
            if is_stock_item(getattr(line, "item_code", None)):
                # Like ERPNext, a receipt is optional. Without one the invoice either receives the goods itself (Update Stock)
                # or is a plain expense/asset line. A site can make the receipt compulsory in Inventory Settings.
                required = get_list("Inventory Settings", fields=["require_purchase_receipt_for_stock_invoices"], limit=1, ignore_permissions=True)
                if required and required[0].get("require_purchase_receipt_for_stock_invoices"):
                    throw(f"Line {index}: {line.item_code} is a stock item. Inventory Settings require it to be invoiced from a Purchase Receipt.")
                if getattr(doc, "update_stock", 0):
                    if not getattr(doc, "warehouse", None):
                        throw("Select the Warehouse that receives the goods when Update Stock is ticked.")
                    if dec(getattr(line, "quantity", 0), f"Line {index} quantity") <= 0:
                        throw(f"Line {index}: quantity must be greater than zero.")
                    line.valuation_rate = (Decimal(str(line.amount)) / Decimal(str(line.quantity))).quantize(Decimal("0.000001"))
            continue
        if not receipt_line_name or matched_qty <= 0:
            throw(f"Line {index}: Purchase Receipt Line and a positive GRNI Matched Quantity are required.")
        receipt = get_doc("Purchase Receipt", receipt_name)
        if int(receipt.docstatus or 0) != 1:
            throw(f"Line {index}: only a submitted Purchase Receipt can be matched.")
        if receipt.party != doc.party:
            throw(f"Line {index}: Purchase Receipt supplier must match the Purchase Invoice supplier.")
        if receipt.currency != doc.currency:
            throw(f"Line {index}: Purchase Receipt and Purchase Invoice currencies must match for GRNI matching.")
        receipt_line = next((r for r in (receipt.lines or []) if str(getattr(r, "name", "")) == str(receipt_line_name)), None)
        if not receipt_line:
            throw(f"Line {index}: Purchase Receipt Line does not belong to the selected Purchase Receipt.")
        if receipt_line.item_code != line.item_code:
            throw(f"Line {index}: invoiced item must match the Purchase Receipt Line item.")
        invoice_factor = dec(getattr(line, "conversion_factor", 1) or 1, "Invoice conversion factor")
        receipt_factor = dec(getattr(receipt_line, "conversion_factor", 1) or 1, "Receipt conversion factor")
        if invoice_factor <= 0 or receipt_factor <= 0:
            throw(f"Line {index}: invoice and receipt conversion factors must be greater than zero.")
        matched_stock_qty = matched_qty * invoice_factor
        received_stock_qty = dec(receipt_line.quantity, "Received Quantity") * receipt_factor
        invoice_stock_qty = dec(getattr(line, "quantity", 0), "Invoiced Quantity") * invoice_factor
        if matched_stock_qty > received_stock_qty:
            throw(f"Line {index}: GRNI Matched Quantity exceeds the received stock quantity.")
        if invoice_stock_qty < matched_stock_qty:
            throw(f"Line {index}: GRNI Matched Quantity cannot exceed the invoiced stock quantity.")
        if dec(getattr(receipt_line, "valuation_rate", 0), "Receipt Valuation Rate") <= 0:
            throw(f"Line {index}: the Purchase Receipt Line must have a positive valuation rate.")
        key = (receipt_name, str(receipt_line_name))
        if key in seen:
            throw(f"Line {index}: do not match the same Purchase Receipt Line twice on one invoice.")
        seen.add(key)
        # Submitted and draft invoices reserve quantities; cancelled invoices do not.
        prior_qty = Decimal("0")
        prior_lines = get_list("Purchase Invoice Line", filters={"purchase_receipt": receipt_name, "purchase_receipt_line": str(receipt_line_name)},
                               fields=["parent", "matched_quantity", "conversion_factor"], limit=5000, ignore_permissions=True)
        parents = {r["name"]: int(r.get("docstatus") or 0) for r in get_list("Purchase Invoice", filters=[["name", "in", list({l["parent"] for l in prior_lines}) or [""]]],
                                                                                 fields=["name", "docstatus"], limit=5000, ignore_permissions=True)}
        for other_line in prior_lines:
            if other_line["parent"] == getattr(doc, "name", None) or parents.get(other_line["parent"], 2) == 2:
                continue
            prior_qty += dec(other_line.get("matched_quantity"), "Prior GRNI Matched Quantity") * dec(other_line.get("conversion_factor") or 1, "Prior invoice conversion factor")
        if prior_qty + matched_stock_qty > received_stock_qty:
            throw(f"Line {index}: cumulative invoiced stock quantity would exceed the received stock quantity. Already matched {prior_qty}; received {received_stock_qty}.")


def _inventory_settings_for_grni():
    from velora import get_list, get_doc
    rows = get_list("Inventory Settings", fields=["name", "goods_received_not_invoiced_account", "purchase_price_variance_account"], limit=1, ignore_permissions=True)
    if not rows:
        throw("Inventory Settings are required for GRNI matching.")
    settings = rows[0]
    if not settings.get("purchase_price_variance_account"):
        throw("Configure Purchase Price Variance Account in Inventory Settings before matching a Purchase Invoice to a Purchase Receipt.")
    account = get_doc("Account", settings["purchase_price_variance_account"])
    if account.disabled or account.root_type != "Expense":
        throw("Purchase Price Variance Account must be an active Expense account.")
    return settings



def _validate_quote_or_po_source(doc, source_doctype, label, follow_on):
    """Invoice raised straight from a quotation or purchase order: same party and currency, line links, cumulative quantity within what is left."""
    from velora import get_doc, get_list
    from decimal import Decimal
    from velora_erp.finance.document_flow.conversion import _converted_quantities
    source = get_doc(source_doctype, doc.source_document)
    source._lock_and_check()
    if int(source.docstatus or 0) != 1 or source.party != doc.party:
        throw(f"The invoice must reference a submitted {label} for the same party.")
    if (doc.currency or "").upper() != (source.currency or "").upper() or Decimal(str(doc.exchange_rate or 1)) != Decimal(str(source.exchange_rate or 1)):
        throw(f"Invoice currency and exchange rate must match the source {label}.")
    lines = {str(l.name): l for l in source.lines or []}
    other_kind = "Purchase Receipt" if source_doctype == "Purchase Order" else follow_on
    followed = _converted_quantities(source_doctype, doc.source_document, other_kind)
    previous = {}
    for entry in get_list(doc.doctype, filters={"source_doctype": source_doctype, "source_document": doc.source_document}, fields=["name", "docstatus"], limit=2000, ignore_permissions=True):
        if entry["name"] == getattr(doc, "name", None) or int(entry.get("docstatus") or 0) == 2: continue
        for l in get_doc(doc.doctype, entry["name"], ignore_permissions=True).lines or []:
            k = str(getattr(l, "source_line", "") or ""); previous[k] = previous.get(k, Decimal("0")) + Decimal(str(l.quantity or 0))
    current = {}
    for index, line in enumerate(doc.lines or [], 1):
        key = str(getattr(line, "source_line", "") or "")
        src = lines.get(key)
        if not src: throw(f"Invoice line {index}: source line does not belong to {label} {doc.source_document}.")
        if getattr(line, "item_code", None) != getattr(src, "item_code", None): throw(f"Invoice line {index}: Item Code cannot differ from the source {label} line.")
        current[key] = current.get(key, Decimal("0")) + Decimal(str(line.quantity or 0))
    for key, qty in current.items():
        src = lines[key]
        from velora import db
        is_stock = bool(getattr(src, "item_code", None) and db.exists("Inventory Item", src.item_code) and get_doc("Inventory Item", src.item_code, ignore_permissions=True).is_stock_item)
        stock_received = followed.get(key, Decimal("0")) if (is_stock or source_doctype != "Purchase Order") else Decimal("0")
        left = Decimal(str(src.quantity)) - previous.get(key, Decimal("0")) - stock_received
        if qty > left:
            throw(f"{getattr(src, 'item_code', None) or 'Line'}: invoiced quantity {qty} exceeds the {left} still open on {label} {doc.source_document}.")


def _validate_sales_order_invoice_source(doc):
    """Validate source order identity and cumulative invoiced quantity on sales invoices."""
    from velora import get_doc, get_list
    from decimal import Decimal
    source_type = getattr(doc, "source_doctype", None)
    source_name = getattr(doc, "source_document", None)
    if source_type == "Delivery Note" or any(getattr(line, "source_document", None) for line in doc.lines or []) or \
            (not source_type and not source_name):
        # lines pulled from several orders or deliveries (or typed in by hand) carry their own source
        from velora_erp.finance.fulfilment import validate_sales_sources
        return validate_sales_sources(doc)
    if source_type == "Sales Quotation" and source_name:
        return _validate_quote_or_po_source(doc, "Sales Quotation", "Sales Quotation", "Sales Order")
    if source_type != "Sales Order" or not source_name:
        throw("Sales Invoice source must be a valid Sales Order or Sales Quotation.")
    order = get_doc("Sales Order", source_name)
    order._lock_and_check()
    if int(order.docstatus or 0) != 1 or order.party != doc.party:
        throw("Sales Invoice must reference a submitted Sales Order for the same customer.")
    if (doc.currency or "").upper() != (order.currency or "").upper() or Decimal(str(doc.exchange_rate or 1)) != Decimal(str(order.exchange_rate or 1)):
        throw("Sales Invoice currency and exchange rate must match the source Sales Order.")
    source_lines = {str(getattr(line, "name", "")): line for line in order.lines or []}
    previous = {}
    invoices = get_list("Sales Invoice", filters={"source_doctype": "Sales Order", "source_document": source_name}, fields=["name", "docstatus"], limit=5000, ignore_permissions=True)
    for entry in invoices:
        if entry["name"] == getattr(doc, "name", None) or int(entry.get("docstatus") or 0) == 2: continue
        other = get_doc("Sales Invoice", entry["name"], ignore_permissions=True)
        for line in other.lines or []:
            key = str(getattr(line, "source_line", "") or "")
            if key: previous[key] = previous.get(key, Decimal("0")) + Decimal(str(getattr(line, "quantity", 0) or 0))
    current = {}
    for index, line in enumerate(doc.lines or [], 1):
        key = str(getattr(line, "source_line", "") or "")
        if not key: throw(f"Invoice line {index}: source Sales Order line is required.")
        source = source_lines.get(key)
        if not source: throw(f"Invoice line {index}: source line does not belong to Sales Order {source_name}.")
        if getattr(line, "item_code", None) != getattr(source, "item_code", None):
            throw(f"Invoice line {index}: Item Code cannot differ from the source Sales Order line.")
        for target_field, source_field in (("rate", "rate"), ("discount_percentage", "discount_percentage"), ("discount_amount", "discount_amount"), ("tax_rate", "tax_rate")):
            left = Decimal(str(getattr(line, target_field, 0) or 0))
            right = Decimal(str(getattr(source, source_field, 0) or 0))
            if left != right:
                throw(f"Invoice line {index}: {target_field.replace('_', ' ').title()} must preserve the approved Sales Order value.")
        if getattr(line, "account", None) != getattr(source, "revenue_account", None):
            throw(f"Invoice line {index}: Revenue Account must match the Sales Order line.")
        if (getattr(line, "tax_account", None) or None) != (getattr(source, "tax_account", None) or None):
            throw(f"Invoice line {index}: Tax Account must match the Sales Order line.")
        if (getattr(line, "tax_code", None) or None) != (getattr(source, "tax_code", None) or None):
            throw(f"Invoice line {index}: Tax Code must match the Sales Order line.")
        if Decimal(str(getattr(line, "conversion_factor", 1) or 1)) != Decimal(str(getattr(source, "conversion_factor", 1) or 1)):
            throw(f"Invoice line {index}: Stock UOM Conversion Factor must match the Sales Order line.")
        qty = Decimal(str(getattr(line, "quantity", 0) or 0))
        if qty <= 0: throw(f"Invoice line {index}: invoiced quantity must be positive.")
        current[key] = current.get(key, Decimal("0")) + qty
    from velora_erp.finance.document_flow.sales_invoicing import _is_stock_item, delivered_quantity_for_order_line
    for key, qty in current.items():
        source_line = source_lines[key]
        ordered = Decimal(str(getattr(source_line, "quantity", 0) or 0))
        cumulative = previous.get(key, Decimal("0")) + qty
        if cumulative > ordered:
            throw(f"Sales Order line {key}: cumulative invoiced quantity exceeds the ordered quantity {ordered}.")
        if _is_stock_item(getattr(source_line, "item_code", None)):
            delivered = delivered_quantity_for_order_line(source_name, key, getattr(source_line, "conversion_factor", 1) or 1)
            if cumulative > delivered:
                throw(f"Sales Order line {key}: cumulative invoiced quantity {cumulative} exceeds submitted delivered quantity {delivered}.")

def _validate_purchase_cost_treatment(doc):
    """Validate prepaid and shared-cost instructions before an invoice can be approved."""
    from datetime import date
    from velora_erp.finance.recognition.schedules import period_dates
    amortised = bool(getattr(doc, "is_amortised_cost", False))
    shared = bool(getattr(doc, "is_shared_cost", False))
    if not amortised and not shared:
        doc.amortisation_preview = []
        if getattr(doc, "cost_allocations", None):
            throw("Remove Cost Allocation rows or enable Is Shared Cost.")
        if getattr(doc, "distribution_rule", None):
            throw("Tick Is Shared Cost to use a Distribution Rule.")
        return
    if amortised:
        if not doc.amortisation_start_date or not doc.amortisation_end_date:
            throw("Amortised costs require Start Date and End Date.")
        if doc.amortisation_end_date < doc.amortisation_start_date:
            throw("Amortisation End Date cannot be earlier than Start Date.")
        if doc.amortisation_frequency not in {"Monthly", "Quarterly", "Half-yearly", "Yearly"}:
            throw("Select a valid amortisation Frequency.")
        _account(doc.prepayment_account, "Asset", "Prepayment Account")
        prepaid = row("Account", doc.prepayment_account, "name", "account_type")
        if not prepaid or prepaid["account_type"] != "PREPAYMENT":
            throw("Prepayment Account must use Account Type Prepayment.")
    if getattr(doc, "distribution_rule", None) and not shared:
        throw("Tick Is Shared Cost to use a Distribution Rule.")
    if shared and getattr(doc, "distribution_rule", None):
        # Same rule table the Payment and Receipt use (Finance Settings > Cost Distribution): turn it into cost-centre allocation rows.
        from velora_erp.finance.cash_transactions import distribution_rows
        rows = distribution_rows(doc.distribution_rule)
        doc.cost_allocations = []
        for centre, pct in rows:
            doc.append("cost_allocations", {"allocation_type": "Cost Centre", "cost_centre": centre, "percentage": pct})
        doc._link_children()   # rows added during validation still need their names and parent links
    allocations = list(getattr(doc, "cost_allocations", None) or []) if shared else []
    if shared:
        if not allocations:
            throw("Add at least one Cost Allocation row when Is Shared Cost is enabled.")
        percentages = []
        for index, allocation in enumerate(allocations, 1):
            pct = Decimal(str(getattr(allocation, "percentage", 0) or 0))
            if not pct.is_finite() or pct <= 0 or pct > 100:
                throw(f"Cost Allocation row {index}: Allocation % must be greater than zero and no more than 100.")
            percentages.append(pct)
            kind = allocation.allocation_type
            if kind == "Cost Centre":
                cc = row("Cost Centre", allocation.cost_centre, "name", "disabled", "is_group")
                if not cc or cc["disabled"] or cc["is_group"]:
                    throw(f"Cost Allocation row {index}: select an active posting Cost Centre, not a group centre.")
            elif kind == "Business Unit":
                bu = row("Business Unit", allocation.business_unit, "name", "disabled")
                if not bu or bu["disabled"]:
                    throw(f"Cost Allocation row {index}: select an active Business Unit.")
            elif kind == "Intercompany":
                if not str(getattr(allocation, "target_company", "") or "").strip():
                    throw(f"Cost Allocation row {index}: Receiving Legal Entity is required.")
                _account(allocation.intercompany_receivable_account, "Asset", f"Cost Allocation row {index} Due From Affiliate Account")
                due_from = row("Account", allocation.intercompany_receivable_account, "name", "account_type")
                if not due_from or due_from["account_type"] != "INTERCOMPANY_RECEIVABLE":
                    throw(f"Cost Allocation row {index}: Due From Affiliate Account must use Account Type Intercompany Receivable.")
            else:
                throw(f"Cost Allocation row {index}: select Cost Centre, Business Unit or Intercompany.")
        if sum(percentages) != Decimal("100"):
            throw(f"Cost Allocation percentages must total exactly 100%; current total is {sum(percentages)}%.")
        # Store calculated transaction-currency values; the last row absorbs rounding residue.
        allocated = Decimal("0")
        for index, allocation in enumerate(allocations, 1):
            if index == len(allocations):
                amount = Decimal(str(doc.net_amount)) - allocated
            else:
                amount = (Decimal(str(doc.net_amount)) * percentages[index - 1] / Decimal("100")).quantize(Decimal("0.01"))
                allocated += amount
            allocation.allocated_amount = amount
    else:
        doc.cost_allocations = []
        doc.distribution_rule = None
    # Shared and amortised costs are service/operating costs. GRNI-matched stock is not eligible.
    if amortised or shared:
        for index, line in enumerate(doc.lines, 1):
            matched = Decimal(str(getattr(line, "matched_quantity", 0) or 0))
            if matched > 0:
                throw(f"Invoice line {index}: GRNI-matched inventory cannot be amortised or shared through this cost allocation feature.")
            _account(line.account, "Expense", f"Invoice line {index} Expense Account")
            if getattr(line, "cost_centre", None):
                cc = row("Cost Centre", line.cost_centre, "name", "disabled", "is_group")
                if not cc or cc["disabled"] or cc["is_group"]:
                    throw(f"Invoice line {index}: select an active posting Cost Centre.")
            if getattr(line, "business_unit", None):
                bu = row("Business Unit", line.business_unit, "name", "disabled")
                if not bu or bu["disabled"]:
                    throw(f"Invoice line {index}: select an active Business Unit.")
    # Rebuild the visible schedule preview from current draft values, never from stale client rows.
    doc.amortisation_preview = []
    if amortised:
        from velora_erp.finance.recognition.schedules import period_dates, period_amount
        dates = period_dates(doc.amortisation_start_date, doc.amortisation_end_date, doc.amortisation_frequency)
        for line in doc.lines:
            shares = allocations if shared else [None]
            for allocation in shares:
                if allocation is None:
                    amount = Decimal(str(line.amount))
                    cc, bu, target = getattr(line, "cost_centre", None), getattr(line, "business_unit", None), None
                else:
                    amount = (Decimal(str(line.amount)) * Decimal(str(allocation.percentage)) / Decimal("100")).quantize(Decimal("0.01"))
                    if allocation is allocations[-1]:
                        prior = sum((Decimal(str(line.amount)) * Decimal(str(a.percentage)) / Decimal("100")).quantize(Decimal("0.01")) for a in allocations[:-1])
                        amount = Decimal(str(line.amount)) - prior
                    cc = allocation.cost_centre if allocation.allocation_type == "Cost Centre" else (getattr(line, "cost_centre", None) if allocation.allocation_type == "Intercompany" else None)
                    bu = allocation.business_unit if allocation.allocation_type == "Business Unit" else (getattr(line, "business_unit", None) if allocation.allocation_type == "Intercompany" else None)
                    target = allocation.target_company if allocation.allocation_type == "Intercompany" else None
                for period, due in enumerate(dates, 1):
                    doc.append("amortisation_preview", {"period_number": period, "recognition_date": due,
                        "amount": period_amount(amount, len(dates), period), "expense_account": line.account,
                        "cost_centre": cc, "business_unit": bu, "target_company": target})
        # Validation runs after the framework's initial child-link pass; re-link
        # newly generated preview rows before the parent is persisted.
        doc._link_children()


def validate_invoice(doc, kind):
    if kind == "Sales":
        _validate_sales_order_invoice_source(doc)
    settings = finance_settings()
    party_type = "Customer" if kind == "Sales" else "Supplier"
    party = row(party_type, doc.party, "name", "disabled", "control_account")
    if not party or party["disabled"]:
        throw(f"Select an active {party_type}.")
    if not doc.invoice_date or not doc.posting_date or not doc.due_date:
        throw("Invoice Date, Posting Date and Due Date are required.")
    if doc.due_date < doc.invoice_date:
        throw("Due Date cannot be earlier than Invoice Date.")
    if not doc.narration or not str(doc.narration).strip():
        # like ERPNext, remarks are optional: the document describes itself when nobody typed one
        doc.narration = f"{doc.doctype} {getattr(doc, 'party_reference', None) or ''} {party_type} {doc.party}".replace("  ", " ").strip()
    doc.currency = (doc.currency or settings["base_currency"]).upper()
    if len(doc.currency) != 3 or not doc.currency.isalpha():
        throw("Transaction Currency must be a three-letter ISO code.")
    from velora_erp.finance.multicurrency import resolve_exchange_rate, apply_base_amounts
    resolve_exchange_rate(doc, "invoice_date")
    rate = Decimal(str(doc.exchange_rate or 0))
    if not rate.is_finite() or rate <= 0:
        throw("Exchange Rate must be a finite amount greater than zero.")
    if not doc.lines:
        throw("At least one invoice line is required.")
    net = tax = Decimal("0")
    if kind == "Purchase" and getattr(doc,"asset_components",None):
        valid_asset_names={getattr(line,"asset_name",None) for line in doc.lines if getattr(line,"is_fixed_asset",False)}
        if any(component.asset_line_name not in valid_asset_names for component in doc.asset_components):
            throw("Every asset component row must reference an existing fixed asset invoice line.")
        if len(valid_asset_names)<sum(1 for line in doc.lines if getattr(line,"is_fixed_asset",False)):
            throw("Asset Line Name must be unique for fixed asset invoice lines when component rows are used.")
    for i, line in enumerate(doc.lines, 1):
        quantity = Decimal(str(getattr(line, "quantity", 0) or 0))
        entered_rate = Decimal(str(getattr(line, "rate", 0) or 0))
        if quantity > 0 and entered_rate > 0:
            discount_pct = Decimal(str(getattr(line, "discount_percentage", 0) or 0))
            discount_amount = Decimal(str(getattr(line, "discount_amount", 0) or 0))
            if discount_pct < 0 or discount_pct >= 100 or discount_amount < 0:
                throw(f"Line {i}: Discounts must be non-negative and percentage discounts must be below 100%.")
            effective_rate = entered_rate * (Decimal("1") - discount_pct / Decimal("100")) - discount_amount
            if effective_rate < 0:
                throw(f"Line {i}: Discounts cannot reduce the unit selling rate below zero.")
            line.amount = (effective_rate * quantity).quantize(Decimal("0.01"), rounding=__import__("decimal").ROUND_HALF_UP)
            if getattr(line, "tax_account", None) and getattr(line, "tax_rate", None) is not None:
                line.tax_amount = (Decimal(str(line.amount)) * Decimal(str(line.tax_rate or 0)) / Decimal("100")).quantize(Decimal("0.01"), rounding=__import__("decimal").ROUND_HALF_UP)
        amount = decimal_amount(line.amount, f"Line {i} net amount")
        tax_amount = decimal_amount(line.tax_amount, f"Line {i} tax amount")
        rate_value = Decimal(str(line.tax_rate or 0))
        if amount <= 0:
            throw(f"Line {i}: Net Amount must be greater than zero.")
        if not quantity.is_finite() or quantity < 0:
            throw(f"Line {i}: Quantity cannot be negative or non-finite.")
        if getattr(line, "item_code", None) and quantity <= 0:
            throw(f"Line {i}: Quantity must be greater than zero when an Item Code is specified.")
        if not line.description or not line.description.strip():
            throw(f"Line {i}: Description is required.")
        if kind == "Sales":
            _account(line.account, "Income", f"Line {i} Revenue Account")
        else:
            matched = Decimal(str(getattr(line, "matched_quantity", 0) or 0))
            unmatched = quantity - matched
            if getattr(line, "is_fixed_asset", False):
                if getattr(doc, "is_amortised_cost", False) or getattr(doc, "is_shared_cost", False):
                    throw("Fixed asset lines cannot be combined with amortised-cost or shared-cost treatment on the same Purchase Invoice.")
                if matched > 0 or getattr(line, "purchase_receipt", None):
                    throw(f"Line {i}: Fixed asset acquisition lines cannot be GRNI-matched inventory lines.")
                _account(line.account, "Asset", f"Line {i} Fixed Asset Account")
                category = row("Fixed Asset Category", line.asset_category, "name", "disabled", "asset_account")
                if not category or category["disabled"]:
                    throw(f"Line {i}: Select an active Fixed Asset Category.")
                if category["asset_account"] != line.account:
                    throw(f"Line {i}: Account must match the selected Fixed Asset Category's Asset Account.")
                if quantity <= 0 or not line.asset_name:
                    throw(f"Line {i}: Fixed Asset Name and a positive quantity are required.")
                if int(line.useful_life_months or 0) <= 0:
                    throw(f"Line {i}: Useful Life must be greater than zero.")
                if Decimal(str(line.residual_value or 0)) * quantity > amount:
                    throw(f"Line {i}: Total Residual Value cannot exceed the line's Net Amount.")
                component_rows=[c for c in (getattr(doc,"asset_components",None) or []) if c.asset_line_name==line.asset_name]
                if component_rows:
                    unit_amount=amount/quantity
                    component_cost=sum((Decimal(str(c.acquisition_cost or 0)) for c in component_rows),Decimal("0"))
                    component_residual=sum((Decimal(str(c.residual_value or 0)) for c in component_rows),Decimal("0"))
                    if abs(component_cost-unit_amount)>Decimal("0.01"): throw(f"Line {i}: Component costs must reconcile to the per-asset invoice amount.")
                    if abs(component_residual-Decimal(str(line.residual_value or 0)))>Decimal("0.01"): throw(f"Line {i}: Component residual values must reconcile to residual value per asset.")
            elif unmatched > 0:
                _account(line.account, "Expense", f"Line {i} Expense Account")
        if tax_amount:
            if not line.tax_account:
                throw(f"Line {i}: Tax Account is required when Tax Amount is entered.")
            _account(line.tax_account, "Liability" if kind == "Sales" else "Asset", f"Line {i} Tax Account")
        if rate_value < 0 or rate_value > 100:
            throw(f"Line {i}: Tax Rate must be between 0 and 100 percent.")
        net += amount
        tax += tax_amount
    if net <= 0:
        throw("Invoice total must be greater than zero.")
    doc.net_amount, doc.tax_amount, doc.grand_total = net, tax, net + tax
    apply_base_amounts(doc, net_field="net_amount", tax_field="tax_amount", total_field="grand_total")
    if kind == "Purchase":
        if getattr(doc, "source_doctype", None) == "Purchase Order" and getattr(doc, "source_document", None):
            _validate_quote_or_po_source(doc, "Purchase Order", "Purchase Order", "Purchase Receipt")
        _validate_grni_matches(doc)
        _validate_purchase_cost_treatment(doc)
    expected_root = "Asset" if kind == "Sales" else "Liability"
    _account(party["control_account"], expected_root, f"{party_type} Control Account")
    validate_approval_transition(doc)


class InvoicePostingAdapter:
    def __init__(self, kind): self.kind = kind
    def build_posting(self, source):
        is_sales = self.kind == "Sales"
        party_type = "Customer" if is_sales else "Supplier"
        party = row(party_type, source.party, "name", "control_account")
        lines = []
        # Receivables debit / Payables credit for the full gross invoice.
        lines.append(PostingLine(account=party["control_account"], debit=source.grand_total if is_sales else 0, credit=0 if is_sales else source.grand_total, party_type=party_type, party=source.party, line_description=f"{self.kind} invoice {source.name}", transaction_date=source.invoice_date, due_date=source.due_date, external_reference=source.party_reference or None))
        for line in source.lines:
            if is_sales:
                lines.append(PostingLine(account=line.account, debit=0, credit=line.amount, line_description=line.description, cost_centre=line.cost_centre or None, transaction_date=source.invoice_date))
            else:
                matched_qty = Decimal(str(getattr(line, "matched_quantity", 0) or 0))
                if matched_qty > 0:
                    from velora import get_doc
                    settings = _inventory_settings_for_grni()
                    receipt = get_doc("Purchase Receipt", line.purchase_receipt)
                    receipt_line = next(r for r in (receipt.lines or []) if str(getattr(r, "name", "")) == str(line.purchase_receipt_line))
                    invoice_qty = Decimal(str(getattr(line, "quantity", 0) or 0))
                    invoice_amount = Decimal(str(line.amount))
                    matched_invoice_amount = invoice_amount * matched_qty / invoice_qty
                    unmatched_invoice_amount = invoice_amount - matched_invoice_amount
                    invoice_factor = Decimal(str(getattr(line, "conversion_factor", 1) or 1))
                    receipt_factor = Decimal(str(getattr(receipt_line, "conversion_factor", 1) or 1))
                    matched_stock_qty = matched_qty * invoice_factor
                    matched_receipt_qty = matched_stock_qty / receipt_factor
                    receipt_base_value = Decimal(str(receipt_line.valuation_rate)) * matched_receipt_qty * Decimal(str(receipt.exchange_rate or 1))
                    invoice_base_value = matched_invoice_amount * Decimal(str(source.exchange_rate or 1))
                    grni_transaction_value = receipt_base_value / Decimal(str(source.exchange_rate or 1))
                    lines.append(PostingLine(account=settings["goods_received_not_invoiced_account"], debit=grni_transaction_value, line_description=f"Clear GRNI: {line.description}", transaction_date=source.invoice_date, source_line_reference=str(line.purchase_receipt_line), item=line.item_code, warehouse=receipt.warehouse))
                    variance_base = invoice_base_value - receipt_base_value
                    variance_transaction = abs(variance_base) / Decimal(str(source.exchange_rate or 1))
                    if variance_base > 0:
                        lines.append(PostingLine(account=settings["purchase_price_variance_account"], debit=variance_transaction, line_description=f"Purchase price variance: {line.description}", transaction_date=source.invoice_date, source_line_reference=str(line.purchase_receipt_line)))
                    elif variance_base < 0:
                        lines.append(PostingLine(account=settings["purchase_price_variance_account"], credit=variance_transaction, line_description=f"Purchase price variance: {line.description}", transaction_date=source.invoice_date, source_line_reference=str(line.purchase_receipt_line)))
                    if unmatched_invoice_amount > 0:
                        lines.append(PostingLine(account=line.account, debit=unmatched_invoice_amount, line_description=f"Unmatched purchase quantity: {line.description}", cost_centre=line.cost_centre or None, business_unit=getattr(line, "business_unit", None) or None, transaction_date=source.invoice_date))
                elif getattr(line, "is_fixed_asset", False):
                    asset_names = [name.strip() for name in str(getattr(line, "created_assets", "") or "").split(",") if name.strip()]
                    quantity = Decimal(str(getattr(line, "quantity", 0) or 0))
                    if not asset_names or quantity != Decimal(len(asset_names)):
                        throw(f"Fixed asset invoice line {line.description} has no matching created asset records.")
                    unit_amount = Decimal(str(line.amount)) / quantity
                    prior_amount = Decimal("0")
                    for asset_index, asset_name in enumerate(asset_names, 1):
                        amount = Decimal(str(line.amount)) - prior_amount if asset_index == len(asset_names) else unit_amount
                        prior_amount += amount
                        lines.append(PostingLine(account=line.account, debit=amount, asset=asset_name,
                            line_description=f"Fixed asset acquisition: {line.description}",
                            cost_centre=line.cost_centre or None, business_unit=getattr(line, "business_unit", None) or None,
                            transaction_date=source.invoice_date))
                elif getattr(source, "is_amortised_cost", False) or getattr(source, "is_shared_cost", False):
                    allocations = list(source.cost_allocations or []) if getattr(source, "is_shared_cost", False) else [None]
                    prior = Decimal("0")
                    for allocation_index, allocation in enumerate(allocations, 1):
                        if allocation is None:
                            share_amount = Decimal(str(line.amount))
                            account = source.prepayment_account if getattr(source, "is_amortised_cost", False) else line.account
                            cost_centre = getattr(line, "cost_centre", None)
                            business_unit = getattr(line, "business_unit", None)
                            description = line.description
                        else:
                            if allocation_index == len(allocations):
                                share_amount = Decimal(str(line.amount)) - prior
                            else:
                                share_amount = (Decimal(str(line.amount)) * Decimal(str(allocation.percentage)) / Decimal("100")).quantize(Decimal("0.01"))
                                prior += share_amount
                            if allocation.allocation_type == "Intercompany":
                                account = allocation.intercompany_receivable_account
                                cost_centre = None
                                business_unit = None
                                description = f"Shared cost receivable from {allocation.target_company}: {line.description}"
                            else:
                                account = source.prepayment_account if getattr(source, "is_amortised_cost", False) else line.account
                                cost_centre = allocation.cost_centre if allocation.allocation_type == "Cost Centre" else None
                                business_unit = allocation.business_unit if allocation.allocation_type == "Business Unit" else None
                                description = line.description
                        if share_amount > 0:
                            lines.append(PostingLine(account=account, debit=share_amount, line_description=description,
                                cost_centre=cost_centre or None, business_unit=business_unit or None, transaction_date=source.invoice_date))
                else:
                    from velora import get_doc
                    debit_account = line.account
                    if getattr(source, "update_stock", 0) and not getattr(line, "purchase_receipt", None):
                        from velora_erp.finance.inventory.ledger import is_stock_item, inventory_settings, _asset_account
                        if is_stock_item(getattr(line, "item_code", None)):
                            debit_account = _asset_account(get_doc("Inventory Item", line.item_code, ignore_permissions=True), inventory_settings())
                    lines.append(PostingLine(account=debit_account, debit=line.amount, line_description=line.description, cost_centre=line.cost_centre or None, business_unit=getattr(line, "business_unit", None) or None, transaction_date=source.invoice_date))
            if decimal_amount(line.tax_amount, "Tax Amount"):
                lines.append(PostingLine(account=line.tax_account, debit=0 if is_sales else line.tax_amount, credit=line.tax_amount if is_sales else 0, line_description=f"Tax: {line.description}", transaction_date=source.invoice_date, tax_code=line.tax_code or None, tax_rate=line.tax_rate or 0, taxable_amount=line.amount, tax_amount=line.tax_amount))
        return PostingInstruction(posting_date=source.posting_date, currency=source.currency, exchange_rate=source.exchange_rate, idempotency_key=f"{self.kind.lower()}-invoice:{source.name}:original", lines=tuple(lines), remarks=source.narration)


def submit_invoice(doc, kind):
    ensure_approved(doc, required=True)
    if kind == "Purchase":
        # Lock receipt headers before the final quantity check. The lock and
        # invoice posting share the source submit transaction, preventing two
        # concurrent supplier invoices from consuming the same GRNI quantity.
        receipt_names = sorted({getattr(line, "purchase_receipt", None) for line in (doc.lines or []) if getattr(line, "purchase_receipt", None)})
        from velora import get_doc
        for receipt_name in receipt_names:
            get_doc("Purchase Receipt", receipt_name)._lock_and_check()
        _validate_grni_matches(doc)
    batch = post_source_document(doc, InvoicePostingAdapter(kind))
    persist_posting_batch_link(doc, batch)
    if kind == "Purchase":
        if getattr(doc, "is_amortised_cost", False):
            from velora_erp.finance.recognition.schedules import create_purchase_invoice_schedules
            create_purchase_invoice_schedules(doc)
        if getattr(doc, "is_shared_cost", False):
            for line in doc.lines or []:
                for allocation in doc.cost_allocations or []:
                    if allocation.allocation_type != "Intercompany":
                        continue
                    share = (Decimal(str(line.amount)) * Decimal(str(allocation.percentage)) / Decimal("100")).quantize(Decimal("0.01"))
                    # Last allocation row absorbs any rounding residue, matching the ledger split.
                    if allocation is doc.cost_allocations[-1]:
                        prior = sum((Decimal(str(line.amount)) * Decimal(str(a.percentage)) / Decimal("100")).quantize(Decimal("0.01")) for a in doc.cost_allocations[:-1])
                        share = Decimal(str(line.amount)) - prior
                    if share <= 0:
                        continue
                    from velora import new_doc
                    new_doc("Intercompany Cost Allocation", source_invoice=doc.name, source_line=str(getattr(line, "name", "")),
                        target_company=allocation.target_company, expense_account=line.account,
                        due_from_account=allocation.intercompany_receivable_account, amount=share,
                        currency=doc.currency, exchange_rate=doc.exchange_rate,
                        is_amortised_cost=1 if getattr(doc, "is_amortised_cost", False) else 0,
                        frequency=doc.amortisation_frequency if getattr(doc, "is_amortised_cost", False) else None,
                        start_date=doc.amortisation_start_date if getattr(doc, "is_amortised_cost", False) else None,
                        end_date=doc.amortisation_end_date if getattr(doc, "is_amortised_cost", False) else None,
                        status="Pending Counterparty Posting").insert(ignore_permissions=True)
    return batch
