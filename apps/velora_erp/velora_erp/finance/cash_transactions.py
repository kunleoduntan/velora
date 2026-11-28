"""Shared validation and posting adapters for universal Receipt and Payment documents."""
from __future__ import annotations
from decimal import Decimal
from velora import throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import (
    decimal_amount, ensure_approved, finance_settings, persist_posting_batch_link,
    validate_approval_transition,
)
from velora_erp.finance.validation import row

RECEIPT_PURPOSES = {
    "Customer Receipt": ("Customer", "receivable"),
    "Customer Refund Recovery": ("Customer", "receivable"),
    "Other Income": (None, None),
    "Supplier Refund": ("Supplier", "supplier_refund"),
    "Loan Received": (None, None),
    "Capital Introduced": (None, None),
    "Tax Refund": (None, None),
    "Customer Advance": ("Customer", "customer_advance"),
    "Deferred Income": (None, None),
    "Employee Repayment": ("Employee", "employee_asset"),
    "Other Receipt": (None, None),
}
PAYMENT_PURPOSES = {
    "Supplier Payment": ("Supplier", "payable"),
    "Expense Payment": (None, None),
    "Customer Refund": ("Customer", "receivable"),
    "Employee Reimbursement": ("Employee", "employee_liability"),
    "Employee Advance": ("Employee", "employee_asset"),
    "Loan Repayment": (None, None),
    "Asset Acquisition": (None, None),
    "Prepayment": (None, None),
    "Supplier Advance": ("Supplier", "supplier_asset"),
    "Tax Payment": (None, None),
    "Other Payment": (None, None),
    "Lease Payment": (None, None),
}


def _account_root(account_name):
    from velora_erp.finance.validation import row
    account = row("Account", account_name, "name", "root_type", "disabled", "account_group", "account_type")
    if not account or account["disabled"]:
        throw(f"Account {account_name!r} does not exist or is disabled.")
    return account["root_type"]


def _validate_party_account(party_type, party_name, account_name, role):
    if not party_type and not party_name:
        return
    if not party_type or not party_name:
        throw("Both Party Type and Party are required when either is supplied.")
    if party_type not in {"Customer", "Supplier", "Employee"}:
        throw("Party Type must be Customer, Supplier or Employee.")
    party_fields = {"Customer": ("name", "disabled", "control_account", "advance_account"),
                    "Supplier": ("name", "disabled", "control_account", "advance_account"),
                    "Employee": ("name", "disabled", "default_payable_account", "advance_account")}[party_type]
    party = row(party_type, party_name, *party_fields)
    if not party or party["disabled"]:
        throw(f"Select an active {party_type}.")
    if role == "receivable" and party_type == "Customer" and party.get("control_account") != account_name:
        throw(f"Account {account_name} must be the selected customer's Receivables Control Account.")
    if role == "payable" and party_type == "Supplier" and party.get("control_account") != account_name:
        throw(f"Account {account_name} must be the selected supplier's Payables Control Account.")
    if role == "supplier_asset" and party_type == "Supplier" and party.get("advance_account") != account_name:
        throw(f"Account {account_name} must be the selected supplier's configured Supplier Advance Account.")
    if role == "supplier_refund" and party_type == "Supplier" and account_name not in {party.get("control_account"), party.get("advance_account")}:
        throw(f"Account {account_name} must be the selected supplier's Payables or Supplier Advance Account.")
    if role == "customer_advance" and party_type == "Customer" and party.get("advance_account") != account_name:
        throw(f"Account {account_name} must be the selected customer's configured Customer Advance Account.")
    if role == "employee_asset" and party_type == "Employee":
        if party.get("advance_account") and party["advance_account"] != account_name:
            throw(f"Account {account_name} is not the selected employee's configured advance/receivable account.")
    if role == "employee_liability" and party_type == "Employee":
        if party.get("default_payable_account") and party["default_payable_account"] != account_name:
            throw(f"Account {account_name} is not the selected employee's configured payable account.")


def _validate_lines(doc, direction):
    if not doc.lines:
        throw("At least one transaction line is required.")
    required_party, account_role = (RECEIPT_PURPOSES if direction == "Receipt" else PAYMENT_PURPOSES)[doc.purpose]
    debit_total = credit_total = Decimal("0")
    expected_side = "Credit" if direction == "Receipt" else "Debit"
    for index, line in enumerate(doc.lines, 1):
        amount = decimal_amount(line.amount, f"Line {index} amount")
        if amount <= 0:
            throw(f"Line {index}: amount must be greater than zero.")
        if not line.account:
            throw(f"Line {index}: Account is required.")
        side = (line.entry_side or expected_side).strip().title()
        if side not in {"Debit", "Credit"}:
            throw(f"Line {index}: Entry Side must be Debit or Credit.")
        if required_party and side == expected_side and line.party_type != required_party:
            throw(f"{doc.purpose} requires Party Type {required_party} on its control-account line.")
        if required_party and side == expected_side and not line.party:
            throw(f"Line {index}: select the {required_party}.")
        if line.party_type and line.party:
            _validate_party_account(line.party_type, line.party, line.account, account_role)
        allocation = decimal_amount(line.allocation_amount, f"Line {index} allocation amount")
        if allocation > amount:
            throw(f"Line {index}: Allocation Amount cannot exceed the transaction line amount.")
        if allocation and not line.invoice_reference:
            throw(f"Line {index}: Invoice / Source Reference is required when an allocation amount is entered.")
        root = _account_root(line.account)
        purpose_roots = {
            "Loan Received": ("Liability", "Credit"), "Capital Introduced": ("Equity", "Credit"),
            "Deferred Income": ("Liability", "Credit"), "Tax Refund": ("Asset", "Credit"),
            "Loan Repayment": ("Liability", "Debit"), "Asset Acquisition": ("Asset", "Debit"),
            "Prepayment": ("Asset", "Debit"), "Tax Payment": ("Liability", "Debit"),
        }
        expected = purpose_roots.get(doc.purpose)
        if expected and (root != expected[0] or side != expected[1]):
            throw(f"{doc.purpose} requires a {expected[1]} posting to a {expected[0]} account.")
        if required_party and side == expected_side:
            if direction == "Receipt" and required_party == "Customer" and account_role == "receivable" and root != "Asset":
                throw(f"Line {index}: Customer receipts must credit an Asset receivables account.")
            if direction == "Receipt" and required_party == "Supplier" and root not in {"Asset", "Liability"}:
                throw(f"Line {index}: Supplier refunds must credit a Supplier Payables or Supplier Advance account.")
            if direction == "Receipt" and required_party == "Customer" and account_role == "customer_advance" and root != "Liability":
                throw(f"Line {index}: Customer advances must credit a Liability customer advance account.")
            if direction == "Payment" and required_party == "Supplier" and account_role == "payable" and root != "Liability":
                throw(f"Line {index}: Supplier payments must debit a Liability payables account.")
            if direction == "Payment" and required_party == "Supplier" and account_role == "supplier_asset" and root != "Asset":
                throw(f"Line {index}: Supplier advances must debit an Asset supplier advance account.")
            if direction == "Payment" and required_party == "Customer" and root != "Asset":
                throw(f"Line {index}: Customer refunds must debit an Asset receivables account.")
            if direction == "Payment" and required_party == "Employee" and account_role == "employee_liability" and root != "Liability":
                throw(f"Line {index}: Employee reimbursements must debit a Liability employee payable account.")
            if direction == "Payment" and required_party == "Employee" and account_role == "employee_asset" and root != "Asset":
                throw(f"Line {index}: Employee advances must debit an Asset employee receivable account.")
        if side == "Debit": debit_total += amount
        else: credit_total += amount
    cash_amount = credit_total - debit_total if direction == "Receipt" else debit_total - credit_total
    if cash_amount <= 0:
        throw(f"The accounting lines do not produce a positive {direction.lower()} cash movement.")
    return cash_amount


def distribution_rows(rule):
    """Cost centres and percentages of a rule, read from the Cost Distribution table in Finance Settings."""
    from velora import get_doc, get_list
    settings = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)
    if not settings:
        throw("Finance Settings must be configured before cost distribution can be used.")
    table = get_doc("Finance Settings", settings[0]["name"], ignore_permissions=True).cost_distribution_lines or []
    rows = [(l.cost_centre, Decimal(str(l.percentage))) for l in table if (l.rule_name or "").strip() == rule]
    if not rows:
        throw(f"Cost Distribution rule {rule!r} is not defined in Finance Settings.")
    if sum(p for _, p in rows) != Decimal("100"):
        throw(f"Cost Distribution rule {rule!r} must total 100%.")
    return rows


def split_amount(amount, rows):
    """Split an amount by percentage to the cent; the last row absorbs the rounding."""
    amount = Decimal(str(amount)); out = []; used = Decimal("0")
    for index, (cc, pct) in enumerate(rows, 1):
        share = amount - used if index == len(rows) else (amount * pct / Decimal("100")).quantize(Decimal("0.01"))
        used += share
        out.append((cc, share))
    return out


def _validate_cost_treatment(doc, direction):
    if getattr(doc, "is_shared_cost", 0):
        if not doc.distribution_rule:
            throw("Select the Distribution Rule that shares this cost.")
        distribution_rows(doc.distribution_rule)
    if getattr(doc, "is_amortised_cost", 0):
        needed = "Prepayment" if direction == "Payment" else "Deferred Income"
        if doc.purpose != needed:
            throw(f"Only a {direction} with purpose {needed} can be amortised.")
        if not (doc.amortisation_start_date and doc.amortisation_end_date):
            throw("Amortisation Start Date and End Date are required.")
        if str(doc.amortisation_end_date) < str(doc.amortisation_start_date):
            throw("Amortisation End Date cannot be before Start Date.")
        if not doc.recognition_account:
            throw("Select the account the amount is recognised in over time.")


_CONTROL_ACCOUNT = {"receivable": "control_account", "payable": "control_account", "customer_advance": "advance_account",
                    "supplier_asset": "advance_account", "employee_asset": "advance_account", "employee_liability": "default_payable_account"}


def _header_party(doc):
    """The one party picked on the form (Customer, Supplier or Employee) as (type, name)."""
    kind = getattr(doc, "party_type", None) or ""
    name = getattr(doc, {"Customer": "customer", "Supplier": "supplier", "Employee": "employee"}.get(kind, "customer"), None) if kind else None
    return (kind, name) if kind and name else (None, None)


def single_line_to_lines(doc, direction):
    """A normal payment or receipt is ONE amount: no table to fill in. Build the single accounting line from the form's Amount,
    Account and party. When the table already has lines (several accounts, or Apply to Invoices) the lines rule and the form's
    Amount simply becomes their total."""
    auto = getattr(doc, "single_line", 0) and len(doc.lines or []) == 1 and not (doc.lines[0].invoice_reference or doc.lines[0].allocation_amount)
    if auto:
        doc.lines = []                                     # the form's Amount changed: build the one line again
    if doc.lines:
        doc.single_line = 0                                # several lines (or settled invoices): the lines rule
        return
    amount = decimal_amount(getattr(doc, "amount", 0) or 0, "Amount")
    if amount <= 0:
        throw("Enter the Amount (or add lines under More Lines).")
    purposes = RECEIPT_PURPOSES if direction == "Receipt" else PAYMENT_PURPOSES
    party_type, party = _header_party(doc)
    required_party, role = purposes.get(doc.purpose, (None, None))
    if required_party and not party:
        throw(f"{doc.purpose} needs the {required_party}: pick the {required_party} above.")
    if required_party and party_type != required_party:
        throw(f"{doc.purpose} is for a {required_party}, not a {party_type or 'blank party'}.")
    account = getattr(doc, "account", None)
    if not account and party:
        found = row(party_type, party, "name", _CONTROL_ACCOUNT.get(role or "payable", "control_account"))
        account = (found or {}).get(_CONTROL_ACCOUNT.get(role or "payable", "control_account"))
        if not account:
            throw(f"{party_type} {party} has no account set up for this {direction.lower()}. Choose the Account yourself or set it on the {party_type}.")
    if not account:
        throw("Choose the Account, or pick the customer, supplier or employee.")
    doc.single_line = 1
    doc.append("lines", {"account": account, "entry_side": "Credit" if direction == "Receipt" else "Debit", "amount": amount,
                         "party_type": party_type, "party": party, "description": doc.narration or None})
    for index, child in enumerate(doc.lines, 1):
        child.idx = index
        child._prepare()
    doc._link_children()


def validate_cash_document(doc, direction):
    single_line_to_lines(doc, direction)
    settings = finance_settings()
    date_field = "receipt_date" if direction == "Receipt" else "payment_date"
    if not getattr(doc, date_field, None) or not doc.posting_date:
        throw(f"{direction} Date and Posting Date are required.")
    if not doc.purpose:
        throw(f"{direction} Purpose is required.")
    purposes = RECEIPT_PURPOSES if direction == "Receipt" else PAYMENT_PURPOSES
    if doc.purpose not in purposes:
        throw(f"Select a valid {direction} Purpose.")
    if getattr(doc, "bank_account", None):
        bank = row("Bank Account", doc.bank_account, "name", "gl_account", "currency", "disabled")
        if not bank or bank["disabled"]:
            throw("Select an active Bank Account.")
        doc.cash_account = bank["gl_account"]
        if bank.get("currency") and doc.currency and str(doc.currency).upper() != bank["currency"]:
            throw(f"Bank Account {doc.bank_account} is held in {bank['currency']}; this {direction} is in {str(doc.currency).upper()}.")
    if not doc.cash_account:
        throw("Select the Bank Account (or the Bank or Cash Account).")
    cash_account = row("Account", doc.cash_account, "name", "root_type", "disabled", "account_type")
    if not cash_account or cash_account["disabled"] or cash_account["root_type"] != "Asset" or cash_account["account_type"] not in {"BANK", "CASH"}:
        throw("Select an active Bank or Cash Account with Account Type Bank or Cash.")
    if not doc.narration or not str(doc.narration).strip():
        doc.narration = f"{doc.doctype} {doc.name or ''}".strip()               # remarks are optional, as in ERPNext
    payment_methods = {"Bank Transfer", "Cash", "Cheque", "Card", "Direct Debit", "Mobile Money", "Other"}
    if doc.payment_method not in payment_methods:
        throw("Select a valid Payment Method.")
    doc.currency = (doc.currency or settings["base_currency"]).upper()
    if len(doc.currency) != 3 or not doc.currency.isalpha():
        throw("Transaction Currency must be a three-letter ISO code.")
    rate = Decimal(str(doc.exchange_rate or 0))
    if not rate.is_finite() or rate <= 0:
        throw("Exchange Rate must be a finite amount greater than zero.")
    if direction == "Payment" and doc.purpose == "Expense Payment" and not (doc.beneficiary or "").strip():
        throw("Payee / Beneficiary is required for Expense Payment.")
    total = _validate_lines(doc, direction)
    doc.total_amount = total
    doc.amount = total
    _validate_cost_treatment(doc, direction)
    from velora_erp.finance.invoice_settlement import validate_allocations
    validate_allocations(doc, direction)
    expected_side = "Credit" if direction == "Receipt" else "Debit"
    doc.total_accounting_amount = sum((decimal_amount(line.amount, "Transaction line amount") for line in doc.lines
        if (line.entry_side or expected_side).title() == expected_side), Decimal("0"))
    if direction == "Payment" and doc.purpose == "Lease Payment":
        if not doc.lease_reference or not doc.lease_due_date:
            throw("Lease Contract and Lease Instalment Due Date are required for Lease Payment.")
        from velora import get_doc, get_list
        lease = get_doc("Fixed Asset Lease", doc.lease_reference, ignore_permissions=True)
        # Serialise settlements for this lease so two different Payment documents
        # cannot concurrently settle the same instalment.
        lease._lock_and_check()
        lease.reload()
        if lease.docstatus != 1 or lease.status != "Active":
            throw("Select an active submitted Fixed Asset Lease.")
        schedule = next((p for p in (lease.payments or []) if str(p.due_date) == str(doc.lease_due_date)), None)
        if not schedule or schedule.payment_status != "Scheduled":
            throw("The selected lease instalment is not an active unpaid scheduled payment.")
        existing = get_list("Payment", filters={"lease_reference": doc.lease_reference, "lease_due_date": doc.lease_due_date, "docstatus": 1}, fields=["name"], limit=50, ignore_permissions=True)
        existing = [p for p in existing if p.get("name") != doc.name]
        if existing:
            throw("A submitted Payment already settles this lease instalment.")
        liability_total = sum((decimal_amount(line.amount, "Lease liability amount") for line in doc.lines if line.account == lease.lease_liability_account), Decimal("0"))
        interest_total = sum((decimal_amount(line.amount, "Lease interest amount") for line in doc.lines if line.account == lease.interest_expense_account), Decimal("0"))
        if liability_total != Decimal(str(schedule.principal_reduction)) or interest_total != Decimal(str(schedule.interest_expense)):
            throw("Lease Payment lines must exactly match the scheduled principal reduction and interest expense.")
        if total != Decimal(str(schedule.payment_amount)):
            throw("Lease Payment total must equal the scheduled instalment amount.")
    validate_approval_transition(doc)
    return settings, total


def _carry_settlements_at_invoice_rate(doc, direction, posting_lines, settings):
    """Settling a foreign-currency invoice at a different rate than it was booked leaves an exchange difference (IAS 21.28).

    The control-account line clears the invoice at its booked base amount, so the party's ledger closes to zero, and the difference goes to
    the realised exchange gain or loss account named in Finance Settings.
    """
    from velora_erp.finance.engine import _money
    from velora_erp.finance.invoice_settlement import SETTLES, carrying_base
    kind = SETTLES.get((direction, doc.purpose))
    base = (settings.get("base_currency") or "").upper()
    if not kind or not doc.currency or doc.currency.upper() == base:
        return
    rate = Decimal(str(doc.exchange_rate or 1))
    places = int(settings.get("decimal_places") if settings.get("decimal_places") is not None else 2)
    taken: dict[str, Decimal] = {}
    carried_any = False
    for source, posted in zip(doc.lines or [], posting_lines[1:]):
        allocated = Decimal(str(source.allocation_amount or 0))
        if not source.invoice_reference or allocated <= 0 or allocated != Decimal(str(source.amount)):
            continue
        carry = carrying_base(kind[0], source.invoice_reference, allocated, taken.get(source.invoice_reference, Decimal(0)), places)
        taken[source.invoice_reference] = taken.get(source.invoice_reference, Decimal(0)) + allocated
        if carry is None:
            continue
        side = "base_debit" if posted["debit"] else "base_credit"
        posted[side] = carry
        posted["fx_role"] = "Carried at original rate"
        carried_any = True
    if not carried_any:
        return
    base_of = lambda line, side: Decimal(str(line.get("base_" + side) or 0)) or _money(Decimal(str(line.get(side) or 0)) * rate, places)
    difference = sum((base_of(l, "debit") for l in posting_lines), Decimal(0)) - sum((base_of(l, "credit") for l in posting_lines), Decimal(0))
    if difference == 0:
        return
    gain = difference > 0                                                # debits exceed credits, so the entity has gained
    account = settings.get("realised_exchange_gain_account" if gain else "realised_exchange_loss_account")
    if not account:
        throw(f"This settlement creates a realised exchange {'gain' if gain else 'loss'} of {abs(difference):,.2f} {base}. Choose the realised exchange "
              f"{'gain' if gain else 'loss'} account in Finance Settings (Foreign Exchange Accounts) and submit again.")
    posting_lines.append({"account": account, "debit": Decimal(0), "credit": Decimal(0), "base_credit" if gain else "base_debit": abs(difference),
                          "fx_role": "Exchange difference", "line_description": f"Realised exchange {'gain' if gain else 'loss'} on {', '.join(sorted(taken))}",
                          "transaction_date": posting_lines[1].get("transaction_date")})


def submit_cash_document(doc, direction):
    ensure_approved(doc, required=True)
    settings = finance_settings()
    total = decimal_amount(doc.total_amount, "Total Amount")
    lines = []
    for line in doc.lines:
        amount = decimal_amount(line.amount, "Transaction line amount")
        lines.append({
            "account": line.account,
            "debit": amount if (line.entry_side or ("Credit" if direction == "Receipt" else "Debit")).title() == "Debit" else Decimal("0"),
            "credit": amount if (line.entry_side or ("Credit" if direction == "Receipt" else "Debit")).title() == "Credit" else Decimal("0"),
            "party_type": line.party_type or None,
            "party": line.party or None,
            "cost_centre": line.cost_centre or None,
            "dimensions": line.dimensions or {},
            "line_description": line.description or doc.narration,
            "transaction_date": (doc.receipt_date if direction == "Receipt" else doc.payment_date),
            "value_date": doc.value_date,
            "external_reference": doc.external_reference or None,
            "settlement_reference": line.settlement_reference or None,
            "source_line_reference": line.invoice_reference or None,
            "tax_code": line.tax_code or None,
            "tax_rate": line.tax_rate or 0,
            "taxable_amount": line.taxable_amount or 0,
            "tax_amount": line.tax_amount or 0,
            "tax_jurisdiction": line.tax_jurisdiction or None,
        })
    if getattr(doc, "is_shared_cost", 0) and doc.distribution_rule:
        rows = distribution_rows(doc.distribution_rule)
        spread = []
        for original, posted in zip(doc.lines, lines):
            if original.party_type or original.invoice_reference:
                spread.append(posted); continue
            whole = posted["debit"] or posted["credit"]
            slices = split_amount(whole, rows)
            tax = Decimal(str(posted.get("tax_amount") or 0)); taxable = Decimal(str(posted.get("taxable_amount") or 0))
            tax_slices = split_amount(tax, rows) if tax else None
            taxable_slices = split_amount(taxable, rows) if taxable else None
            for n, (cc, share) in enumerate(slices):
                piece = dict(posted)
                if posted["debit"]: piece["debit"] = share
                else: piece["credit"] = share
                piece["cost_centre"] = cc
                if tax_slices: piece["tax_amount"] = tax_slices[n][1]
                if taxable_slices: piece["taxable_amount"] = taxable_slices[n][1]
                spread.append(piece)
        lines = spread
    cash_line = {
        "account": doc.cash_account,
        "debit": total if direction == "Receipt" else Decimal("0"),
        "credit": total if direction == "Payment" else Decimal("0"),
        "line_description": f"{direction}: {doc.narration}",
        "value_date": doc.value_date,
        "external_reference": doc.external_reference or None,
    }
    posting_lines = [cash_line, *lines]
    _carry_settlements_at_invoice_rate(doc, direction, posting_lines, settings)
    batch = post_financial_transaction(
        source_doctype=direction,
        source_name=doc.name,
        posting_date=doc.posting_date,
        currency=doc.currency,
        exchange_rate=doc.exchange_rate,
        lines=posting_lines,
        posting_event="Original",
        remarks=doc.narration,
        idempotency_key=f"{direction.lower()}:{doc.name}:original",
    )
    persist_posting_batch_link(doc, batch)
    create_cash_recognition_schedules(doc, direction)
    from velora_erp.finance.invoice_settlement import apply_allocations
    from velora_erp.finance.doctype._utils import db_update as _db_update
    if apply_allocations(doc, direction):
        _db_update(doc, allocation_status="Applied")
    if direction == "Payment" and doc.purpose == "Lease Payment":
        from velora import get_doc
        lease = get_doc("Fixed Asset Lease", doc.lease_reference, ignore_permissions=True)
        schedule = next(p for p in lease.payments if str(p.due_date) == str(doc.lease_due_date))
        from velora_erp.finance.doctype._utils import db_update, db_update_child
        db_update_child("Fixed Asset Lease Payment", schedule.name, payment_status="Paid", payment_reference=doc.name)
        db_update(lease, lease_liability_balance=schedule.closing_liability)
        from velora.activity import record_event
        record_event("integration", f"Lease instalment settled: {lease.name}", doctype="Fixed Asset Lease",
                     document_name=lease.name, changed_fields=["payments.payment_status", "payments.payment_reference"],
                     summary=f"Payment {doc.name} settled the instalment due {doc.lease_due_date}.",
                     metadata={"payment": doc.name, "due_date": str(doc.lease_due_date)})
    return batch



def create_cash_recognition_schedules(doc, direction):
    """Prepayment / Deferred Income: create approval-pending recognition schedules, split by the distribution rule."""
    if not getattr(doc, "is_amortised_cost", 0):
        return []
    from velora import new_doc
    kind = "Prepayment" if direction == "Payment" else "Deferred Income"
    rows = distribution_rows(doc.distribution_rule) if getattr(doc, "is_shared_cost", 0) and doc.distribution_rule else [(None, Decimal("100"))]
    made = []
    for line in doc.lines:
        if line.party_type or line.invoice_reference:
            continue
        for cc, share in split_amount(line.amount, rows):
            if share <= 0:
                continue
            schedule = new_doc("Recognition Schedule", schedule_type=kind, source_doctype=direction, source_document=doc.name,
                start_date=doc.amortisation_start_date, end_date=doc.amortisation_end_date, frequency=doc.amortisation_frequency or "Monthly",
                total_amount=share, balance_account=line.account, recognition_account=doc.recognition_account,
                cost_centre=cc or line.cost_centre or None, approval_status="Pending",
                notes=f"Generated from {direction} {doc.name}; requires independent approval.")
            schedule.insert(ignore_permissions=True)
            if doc.owner and schedule.owner != doc.owner:
                schedule.owner = doc.owner
                schedule.save(ignore_permissions=True)
            made.append(schedule.name)
    return made
