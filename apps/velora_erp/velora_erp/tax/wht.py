"""Withholding tax: the Tax Journal.

Two directions, one document:

* Customer row  - a customer paid us net of tax and gave us a certificate. We hold a credit with the tax authority:
      Dr WHT credit account (asset)        Cr Customer control account (party = customer)
* Supplier row  - we paid a supplier net of tax and must remit the tax:
      Dr Supplier control account (party)  Cr WHT payable account (liability)

A row that names an invoice settles it by the tax amount (the cash receipt / payment settles the net part), under row locks,
and cancelling the journal reopens it. The ledger rows carry tax_code, rate and taxable amount, so the Tax Ledger, WHT
returns and the WHT reports read them without any extra step.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select, update
from velora import Document, db, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.invoice_settlement import _invoice_row, outstanding_of, status_for
from velora_erp.finance.source_documents import decimal_amount, ensure_approved, finance_settings, persist_posting_batch_link, validate_approval_transition
from velora_erp.finance.validation import row
from velora_erp.tax import engine as eng
from velora_erp.tax.service import _date, rules_by_code

ZERO = Decimal("0")
KIND = {"Customer": ("Sales Invoice", "Asset"), "Supplier": ("Purchase Invoice", "Liability"), "Income received": (None, "Asset"), "Payment made": (None, "Liability")}
PARTY = ("Customer", "Supplier")
CREDIT_SIDE = ("Customer", "Income received")      # tax suffered: a credit we hold


def _rule_for(code, on):
    cands = [r for r in rules_by_code(on).get((code or "").strip().upper(), []) if r.tax_type == "WHT"]
    return cands[0] if cands else None


def _rule_account(code):
    for r in get_list("Tax Rule", filters=[["rule_code", "=", (code or "").strip().upper()], ["docstatus", "=", 1], ["approval_status", "=", "Approved"]],
                      fields=["tax_account"], limit=5, ignore_permissions=True):
        if r.get("tax_account"):
            return r["tax_account"]
    return None


def settlements(doc) -> dict:
    """{(invoice doctype, invoice): amount} this journal settles."""
    out: dict = defaultdict(lambda: ZERO)
    for line in doc.lines or []:
        if line.invoice_reference and KIND[line.party_type][0]:
            out[(KIND[line.party_type][0], line.invoice_reference.strip())] += decimal_amount(line.wht_amount, "Tax withheld")
    return dict(out)


class TaxJournal(Document):
    def validate(self):
        base = finance_settings()["base_currency"]
        if not self.posting_date:
            throw("Posting date is required.")
        if not self.narration or not str(self.narration).strip():
            throw("Narration is required.")
        self.currency = (self.currency or base).upper()
        if not self.exchange_rate or float(self.exchange_rate) <= 0:
            throw("Exchange rate must be greater than zero.")
        if not self.lines:
            throw("Add at least one withholding tax row.")
        on = _date(self.posting_date)
        suffered = payable = ZERO
        seen = set()
        for i, line in enumerate(self.lines, 1):
            kind = KIND.get(line.party_type)
            if not kind:
                throw(f"Row {i}: choose Customer or Supplier.")
            if line.party_type in PARTY:
                party = row(line.party_type, line.party, "name", "disabled", "control_account", f"{line.party_type.lower()}_name")
                if not party or party["disabled"]:
                    throw(f"Row {i}: select an active {line.party_type}.")
                if not party["control_account"]:
                    throw(f"Row {i}: {line.party_type} {line.party} has no control account configured.")
                line.party_name = party[f"{line.party_type.lower()}_name"]
            else:
                if not line.party_name and not line.party:
                    throw(f"Row {i}: enter who paid or received the money.")
                line.party_name = line.party_name or line.party
                if not line.counter_account:
                    throw(f"Row {i}: choose the counter account (for example dividend income or dividends payable).")
                ca = row("Account", line.counter_account, "name", "disabled", "is_group")
                if not ca or ca["disabled"] or ca["is_group"]:
                    throw(f"Row {i}: the counter account must be an active posting account.")
                if line.invoice_reference:
                    throw(f"Row {i}: only Customer and Supplier rows can settle an invoice.")
            gross = decimal_amount(line.gross_amount, f"Row {i} taxable amount")
            if gross <= 0:
                throw(f"Row {i}: the taxable amount must be greater than zero.")
            rule = None
            if line.tax_rule:
                line.tax_rule = line.tax_rule.strip().upper()
                rule = _rule_for(line.tax_rule, on)
                if not rule:
                    throw(f"Row {i}: no approved WHT rule {line.tax_rule} is in force on {on}.")
                line.rate = float(rule.rate)
            amount = decimal_amount(line.wht_amount, f"Row {i} tax withheld") if line.wht_amount not in (None, "") else ZERO
            if amount <= 0:
                if not rule:
                    throw(f"Row {i}: enter the tax withheld, or choose a WHT rule to calculate it.")
                amount = eng.calculate(rule, gross).tax_amount
            line.wht_amount = amount
            if amount > gross:
                throw(f"Row {i}: the tax withheld cannot exceed the taxable amount.")
            if not line.tax_account and line.tax_rule:
                line.tax_account = _rule_account(line.tax_rule)
            if not line.tax_account:
                throw(f"Row {i}: choose the tax account (or set one on the rule).")
            acc = row("Account", line.tax_account, "name", "disabled", "root_type", "is_group")
            if not acc or acc["disabled"] or acc["is_group"]:
                throw(f"Row {i}: the tax account must be an active posting account.")
            if acc["root_type"] != kind[1]:
                throw(f"Row {i}: a {line.party_type} row needs a{'n' if kind[1] == 'Asset' else ''} {kind[1].lower()} account "
                      f"({'tax credit receivable' if kind[1] == 'Asset' else 'tax payable'}).")
            if line.invoice_reference:
                line.invoice_reference = line.invoice_reference.strip()
                key = (line.party_type, line.invoice_reference)
                if key in seen:
                    throw(f"Row {i}: invoice {line.invoice_reference} appears twice; combine the rows.")
                seen.add(key)
            if line.party_type in CREDIT_SIDE:
                suffered += amount
            else:
                payable += amount
        self.total_suffered, self.total_payable = suffered, payable
        validate_approval_transition(self)
        self._check_invoices(lock=False)

    def _check_invoices(self, lock):
        for (doctype, name), amount in settlements(self).items():
            inv = _invoice_row(doctype, name, lock=lock)
            if not inv or inv["docstatus"] != 1:
                throw(f"{doctype} {name} is not a submitted invoice.")
            if inv.get("approval_status") not in (None, "Approved"):
                throw(f"{doctype} {name} is not approved.")
            owners = {l.party for l in self.lines if l.invoice_reference == name}
            if owners != {inv["party"]}:
                throw(f"{doctype} {name} belongs to {inv['party']}, not {', '.join(sorted(map(str, owners)))}.")
            if (inv.get("currency") or "").upper() != self.currency:
                throw(f"{doctype} {name} is in {inv.get('currency')}; this journal is in {self.currency}.")
            if amount > outstanding_of(inv):
                throw(f"{doctype} {name} has only {outstanding_of(inv):,.2f} outstanding; the tax withheld is {amount:,.2f}.")

    def before_submit(self):
        from velora_erp.tax.service import settings
        if settings().get("require_wht_certificate"):
            for i, line in enumerate(self.lines, 1):
                if line.party_type in CREDIT_SIDE and not (line.certificate_number or "").strip():
                    throw(f"Row {i}: the customer's withholding tax certificate number is required (Tax Settings).")
        ensure_approved(self, required=True)

    def on_submit(self):
        posting = []
        for i, line in enumerate(self.lines, 1):
            amount = decimal_amount(line.wht_amount, "Tax withheld")
            gross = decimal_amount(line.gross_amount, "Taxable amount")
            rule = _rule_for(line.tax_rule, _date(self.posting_date)) if line.tax_rule else None
            tax = {"tax_jurisdiction": rule.jurisdiction if rule else None, "tax_code": line.tax_rule or None, "tax_rate": line.rate or 0, "taxable_amount": gross, "tax_amount": amount,
                   "base_taxable_amount": gross * Decimal(str(self.exchange_rate)), "base_tax_amount": amount * Decimal(str(self.exchange_rate)), "settlement_reference": line.invoice_reference or None}
            who = f"{line.party_type.lower()} {line.party or line.party_name}"
            text = f"WHT {who}" + (f" ({line.nature.lower()})" if line.nature else "") + (f" - {line.invoice_reference}" if line.invoice_reference else "") + (f" cert {line.certificate_number}" if line.certificate_number else "")
            suffered = line.party_type in CREDIT_SIDE
            if line.party_type in PARTY:
                ctl = row(line.party_type, line.party, "control_account")
                party_leg = {"account": ctl["control_account"], "party_type": line.party_type, "party": line.party, "settlement_reference": line.invoice_reference or None}
            else:
                party_leg = {"account": line.counter_account}
            party_leg.update({"line_description": text, "debit": ZERO if suffered else amount, "credit": amount if suffered else ZERO})
            tax_leg = {"account": line.tax_account, "line_description": text, "debit": amount if suffered else ZERO, "credit": ZERO if suffered else amount, **tax}
            posting += [party_leg, tax_leg]
        self._apply(+1)
        batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.posting_date, currency=self.currency,
                                           exchange_rate=self.exchange_rate, lines=posting, posting_event="Adjustment", remarks=self.narration,
                                           idempotency_key=f"tax-journal:{self.name}")
        persist_posting_batch_link(self, batch)

    def _apply(self, sign):
        self._check_invoices(lock=True) if sign > 0 else None
        for (doctype, name), amount in settlements(self).items():
            table = get_table(doctype)
            with db.transaction() as conn:
                inv = conn.execute(select(table).where(table.c.name == name).with_for_update()).mappings().first()
                if not inv:
                    continue
                settled = max(ZERO, Decimal(str(inv["amount_settled"] or 0)) + sign * amount)
                conn.execute(update(table).where(table.c.name == name).values(amount_settled=settled, payment_status=status_for(inv["grand_total"], settled)))

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted Tax Journal cannot be deleted; cancel it instead.")


def release_settlements(doc, report) -> None:
    """Cancellation rule: give the invoices back what this journal settled."""
    TaxJournal._apply(doc, -1)
    n = len(settlements(doc))
    if n:
        report.note(f"{n} invoice(s) reopened by the tax withheld")
