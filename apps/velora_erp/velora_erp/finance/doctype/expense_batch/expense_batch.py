"""Expense Batch: petty-cash expenses posted in one balanced posting, pre-validated row by row."""
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from velora import Document, db, throw
from velora.db.tables import get_table
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, validate_approval_transition
from velora_erp.finance.validation import row

CENT = Decimal("0.01")
MAX_REPORTED = 25


def D(v):
    return Decimal(str(v if v not in (None, "") else 0))


def _account(name, roots=None, types=None):
    a = row("Account", name, "name", "root_type", "account_type", "disabled", "account_currency")
    if not a or a["disabled"]:
        raise ValueError(f"Account {name!r} does not exist or is disabled.")
    if roots and a["root_type"] not in roots:
        raise ValueError(f"Account {name} must be a {' or '.join(roots)} account.")
    if types and a["account_type"] not in types:
        raise ValueError(f"Account {name} must have Account Type {' or '.join(types)}.")
    return a


def wht_of(amount, rate) -> Decimal:
    return (D(amount) * D(rate) / Decimal("100")).quantize(CENT, ROUND_HALF_UP)


def _existing_duplicates(doc):
    """(date, amount, payee, reference) already paid from this petty cash account by another submitted batch."""
    parent, line = get_table("Expense Batch"), get_table("Expense Batch Line")
    with db.transaction() as conn:
        rows = conn.execute(select(line.c.expense_date, line.c.amount, line.c.payee, line.c.reference, parent.c.name)
                            .select_from(line.join(parent, line.c.parent == parent.c.name))
                            .where(parent.c.docstatus == 1, parent.c.petty_cash_account == doc.petty_cash_account,
                                   parent.c.name != (doc.name or ""))).mappings().all()
    return {(str(r["expense_date"])[:10], D(r["amount"]), (r["payee"] or "").strip().casefold(), (r["reference"] or "").strip().casefold()): r["name"] for r in rows}


class ExpenseBatch(Document):
    def validate(self):
        validate_approval_transition(self)
        if not self.petty_cash_account or not self.posting_date:
            throw("Company, Petty Cash Account and Posting Date are required.")
        if not self.lines:
            throw("At least one expense line is required.")
        errors = []
        try:
            petty = _account(self.petty_cash_account, ["Asset"], ["CASH", "BANK"])
        except ValueError as exc:
            throw(str(exc))
        self.currency = (self.currency or petty.get("account_currency") or "NGN").upper()
        if D(self.exchange_rate) <= 0:
            throw("Exchange Rate must be greater than zero.")
        seen, existing = {}, _existing_duplicates(self)
        gross = wht_total = Decimal("0")
        for i, l in enumerate(self.lines, 1):
            try:
                amount = D(l.amount)
                if amount <= 0:
                    raise ValueError("Gross Amount must be greater than zero.")
                if not l.expense_date:
                    raise ValueError("Expense Date is required.")
                if not (l.payee or "").strip():
                    raise ValueError("Payee is required.")
                _account(l.expense_account, ["Expense", "Asset"])
                rate = D(l.wht_rate)
                if rate < 0 or rate >= 100:
                    raise ValueError("WHT Rate must be at least 0 and below 100.")
                if rate and not self.wht_payable_account:
                    raise ValueError("Select the Withholding Tax Payable Account to deduct WHT.")
                key = (str(l.expense_date)[:10], amount, (l.payee or "").strip().casefold(), (l.reference or "").strip().casefold())
                if (l.reference or "").strip() and not l.allow_duplicate:
                    if key in seen:
                        raise ValueError(f"Duplicate of row {seen[key]} in this batch (same date, amount, payee and reference).")
                    if key in existing:
                        raise ValueError(f"Already paid in {existing[key]} (same date, amount, payee and reference). Tick Allow Duplicate if this is genuinely a second payment.")
                seen.setdefault(key, i)
                gross += amount
                wht_total += wht_of(amount, rate)
            except ValueError as exc:
                errors.append(f"Row {i}: {exc}")
        if self.wht_payable_account:
            try:
                _account(self.wht_payable_account, ["Liability"])
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            shown = errors[:MAX_REPORTED]
            more = f" (and {len(errors) - MAX_REPORTED} more)" if len(errors) > MAX_REPORTED else ""
            throw("Fix these rows before saving: " + " | ".join(shown) + more)
        self.total_expenses, self.total_wht, self.net_cash = gross, wht_total, gross - wht_total

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        lines = []
        for l in self.lines:
            gross, wht = D(l.amount), wht_of(l.amount, l.wht_rate)
            common = {"party_type": None, "party": None, "cost_centre": l.cost_centre or None, "business_unit": l.business_unit or None,
                      "dimensions": l.dimensions or {}, "line_description": f"{l.payee}: {l.description}",
                      "transaction_date": l.expense_date, "external_reference": l.reference or None}
            lines.append({"account": l.expense_account, "debit": gross, "credit": 0, **common})
            lines.append({"account": self.petty_cash_account, "debit": 0, "credit": gross - wht, **common})
            if wht:
                lines.append({"account": self.wht_payable_account, "debit": 0, "credit": wht, **common})
        batch = post_financial_transaction(
            source_doctype=self.doctype, source_name=self.name, posting_date=self.posting_date, currency=self.currency,
            exchange_rate=self.exchange_rate or 1, lines=lines, posting_event="Original",
            remarks=f"Expense batch {self.name}", idempotency_key=f"expense-batch:{self.name}:original")
        self.posting_batch = batch.name
        db_update(self, posting_batch=batch.name)


    def before_delete(self):
        if self.docstatus == 1:
            throw("A posted expense batch cannot be deleted.")
