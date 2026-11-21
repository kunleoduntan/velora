from decimal import Decimal
from velora import Document, get_list, throw
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import decimal_amount, ensure_approved, finance_settings, persist_posting_batch_link, validate_approval_transition
from velora_erp.finance.validation import row

PARTY_RULES = {"Supplier": ("control_account", "supplier_name"), "Customer": ("control_account", "customer_name"), "Employee": ("default_payable_account", "employee_name")}


def _dimension_codes():
    return {str(r["dimension_code"]).upper(): r["dimension_code"] for r in get_list("Accounting Dimension", filters={"disabled": 0}, fields=["dimension_code"], limit=200, ignore_permissions=True)}


def resolve_leg(line, index):
    """Return (account, party_type, party, party_name) for the first leg of a voucher row."""
    if line.account_type == "Account GL":
        account = row("Account", line.party, "name", "disabled")
        if not account or account["disabled"]:
            throw(f"Row {index}: {line.party!r} is not an active general ledger account.")
        return line.party, None, None, line.party
    field, name_field = PARTY_RULES[line.account_type]
    party = row(line.account_type, line.party, "name", "disabled", field, name_field)
    if not party or party["disabled"]:
        throw(f"Row {index}: select an active {line.account_type}.")
    if not party[field]:
        throw(f"Row {index}: {line.account_type} {line.party} has no {field.replace('_', ' ')} configured.")
    return party[field], line.account_type, line.party, party[name_field]


class JournalEntryVoucher(Document):
    def validate(self):
        settings = finance_settings()
        if not self.voucher_date or not self.posting_date:
            throw("Voucher Date and Posting Date are required.")
        if not self.narration or not str(self.narration).strip():
            throw("Narration is required.")
        self.currency = (self.currency or settings["base_currency"]).upper()
        if not self.exchange_rate or float(self.exchange_rate) <= 0:
            throw("Exchange Rate must be greater than zero.")
        if not self.lines:
            throw("Add at least one transaction row.")
        debit = credit = Decimal("0")
        for index, line in enumerate(self.lines, 1):
            amount = decimal_amount(line.amount, f"Row {index} amount")
            if amount <= 0:
                throw(f"Row {index}: Amount must be greater than zero.")
            account, _, _, name = resolve_leg(line, index)
            if account == line.corresponding_account:
                throw(f"Row {index}: the corresponding account must differ from the first account.")
            line.party_name = name
            if line.trans_effect == "Debit": debit += amount
            elif line.trans_effect == "Credit": credit += amount
            else: throw(f"Row {index}: Trans Effect must be Debit or Credit.")
        # every row posts its own opposite leg, so the voucher always balances
        self.total_debit, self.total_credit, self.difference = debit, credit, debit - credit
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        codes = _dimension_codes()
        posting = []
        for index, line in enumerate(self.lines, 1):
            amount = decimal_amount(line.amount, "Amount")
            account, party_type, party, _ = resolve_leg(line, index)
            debit_side = line.trans_effect == "Debit"
            def dims(project, branch):
                out = {}
                if project and "PROJECT" in codes: out[codes["PROJECT"]] = project
                if branch and "BRANCH" in codes: out[codes["BRANCH"]] = branch
                return out
            description = line.transaction_description
            posting.append({"account": account, "debit": amount if debit_side else Decimal("0"), "credit": Decimal("0") if debit_side else amount,
                            "party_type": party_type, "party": party, "cost_centre": line.cost_centre or None,
                            "dimensions": dims(line.project, line.branch), "line_description": description, "transaction_date": line.trans_date})
            posting.append({"account": line.corresponding_account, "debit": Decimal("0") if debit_side else amount, "credit": amount if debit_side else Decimal("0"),
                            "cost_centre": line.corresponding_cost_centre or line.cost_centre or None,
                            "dimensions": dims(line.corresponding_project or line.project, line.branch), "line_description": description, "transaction_date": line.trans_date})
        batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.posting_date, currency=self.currency,
                                           exchange_rate=self.exchange_rate, lines=posting, posting_event="Adjustment", remarks=self.narration,
                                           idempotency_key=f"journal-entry-voucher:{self.name}")
        persist_posting_batch_link(self, batch)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Journal Entry Voucher cannot be deleted.")
