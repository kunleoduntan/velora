"""Customer credit exposure and server-side credit hold/limit enforcement."""
from decimal import Decimal, InvalidOperation
from velora import get_doc, get_list, throw


def _d(value, label):
    try: result = Decimal(str(value if value not in (None, "") else 0))
    except (InvalidOperation, TypeError, ValueError): throw(f"{label} must be numeric.")
    if not result.is_finite(): throw(f"{label} must be finite.")
    return result


def _settings():
    rows = get_list("Finance Settings", fields=["name", "enforce_customer_credit_limit", "include_open_sales_orders_in_credit_exposure"], limit=1, ignore_permissions=True)
    return rows[0] if rows else {"enforce_customer_credit_limit": 1, "include_open_sales_orders_in_credit_exposure": 1}


def receivables_exposure(customer):
    party = get_doc("Customer", customer, ignore_permissions=True)
    account = getattr(party, "control_account", None)
    if not account: throw(f"Customer {customer} has no Receivables Control Account.")
    rows = get_list("Account Ledger Record", filters={"party_type": "Customer", "party": customer, "account": account}, fields=["base_debit", "base_credit"], limit=100000, ignore_permissions=True)
    return sum((_d(r.get("base_debit"), "Receivable debit") - _d(r.get("base_credit"), "Receivable credit") for r in rows), Decimal("0"))


def order_line_gross(line):
    """Line amount plus its tax: invoices are measured on the grand total, so orders are too."""
    amount = _d(getattr(line, "amount", 0), "Order line amount")
    rate = _d(getattr(line, "tax_rate", 0), "Order line tax rate")
    return amount * (Decimal("1") + rate / Decimal("100")) if rate > 0 else amount


def order_gross_total(order):
    return sum((order_line_gross(line) for line in order.lines or []), Decimal("0"))


def open_order_commitment(customer, exclude_order=None):
    orders = get_list("Sales Order", filters={"party": customer, "docstatus": 1}, fields=["name", "document_status"], limit=5000, ignore_permissions=True)
    if len(orders) >= 5000: throw("Credit exposure exceeds the supported order scan. Contact an administrator to run a controlled exposure rebuild.")
    total = Decimal("0")
    for entry in orders:
        if entry["name"] == exclude_order or entry.get("document_status") == "Closed": continue
        order = get_doc("Sales Order", entry["name"], ignore_permissions=True)
        invoiced = {}
        invoices = get_list("Sales Invoice", filters={"source_doctype": "Sales Order", "source_document": order.name}, fields=["name", "docstatus"], limit=5000, ignore_permissions=True)
        for inv in invoices:
            if int(inv.get("docstatus") or 0) == 2: continue
            doc = get_doc("Sales Invoice", inv["name"], ignore_permissions=True)
            for line in doc.lines or []:
                key = str(getattr(line, "source_line", "") or "")
                if key: invoiced[key] = invoiced.get(key, Decimal("0")) + _d(getattr(line, "quantity", 0), "Invoiced quantity")
        for line in order.lines or []:
            qty = max(Decimal("0"), _d(line.quantity, "Ordered quantity") - invoiced.get(str(getattr(line, "name", "")), Decimal("0")))
            line_amount = order_line_gross(line)
            line_qty = _d(line.quantity, "Order line quantity")
            if line_qty > 0:
                fx = _d(getattr(order, "exchange_rate", 1) or 1, "Sales Order exchange rate")
                if fx <= 0: throw(f"Sales Order {order.name} has an invalid exchange rate.")
                total += line_amount * qty / line_qty * fx
    return total


def customer_credit_exposure(customer, *, include_orders=True, exclude_order=None):
    exposure = receivables_exposure(customer)
    if include_orders: exposure += open_order_commitment(customer, exclude_order=exclude_order)
    return max(Decimal("0"), exposure)


def enforce_customer_credit(doc, *, transaction_amount=None, include_orders=True, exclude_order=None):
    """Block hold and over-limit transactions. Credit limit zero means unlimited."""
    settings = _settings()
    if not bool(settings.get("enforce_customer_credit_limit", 1)): return
    customer = get_doc("Customer", doc.party, ignore_permissions=True)
    if getattr(customer, "disabled", 0): throw("The selected customer is disabled.")
    if getattr(customer, "credit_hold", 0): throw(f"Customer {doc.party} is on Credit Hold. Obtain an authorised release before proceeding.")
    limit = _d(getattr(customer, "credit_limit", 0), "Customer credit limit")
    if limit < 0: throw("Customer Credit Limit cannot be negative.")
    if limit == 0: return
    exposure = customer_credit_exposure(doc.party, include_orders=include_orders and bool(settings.get("include_open_sales_orders_in_credit_exposure", 1)), exclude_order=exclude_order)
    amount = _d(transaction_amount if transaction_amount is not None else getattr(doc, "grand_total", 0), "Transaction amount")
    projected = exposure + amount
    if projected > limit:
        throw(f"Customer {doc.party} would exceed the credit limit. Current exposure: {exposure:,.2f}; transaction: {amount:,.2f}; projected exposure: {projected:,.2f}; credit limit: {limit:,.2f}.")
