"""IFRS 9 simplified approach: a lifetime expected-loss provision matrix applied to the ageing of receivables.

The assessment measures the allowance that should exist, compares it with the allowance already in the ledger, and posts only the difference
(a charge, or a release when the matrix needs less). Receivables are read from submitted sales invoices, in the base currency at the booked rate."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from velora import Document, get_list, throw
from velora_erp.finance.ageing import ageing_bucket
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import get_account_balance, post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, finance_settings, validate_approval_transition
from velora_erp.finance.validation import row

BUCKETS = ("Not Due", "1-30 Days", "31-60 Days", "61-90 Days", "Over 90 Days")


def D(v):
    return Decimal(str(v or 0))


def receivable_exposure(as_of) -> dict[str, Decimal]:
    out = {b: Decimal(0) for b in BUCKETS}
    as_of = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)[:10])
    for r in get_list("Sales Invoice", filters=[["docstatus", "=", 1]], fields=["name", "due_date", "grand_total", "amount_settled", "exchange_rate", "posting_date"], limit=100000, ignore_permissions=True):
        if r.get("posting_date") and str(r["posting_date"])[:10] > str(as_of):
            continue
        open_ = (D(r["grand_total"]) - D(r["amount_settled"])) * D(r["exchange_rate"] or 1)
        if open_ <= 0:
            continue
        due = r["due_date"] if isinstance(r["due_date"], date) else date.fromisoformat(str(r["due_date"])[:10])
        out[ageing_bucket((as_of - due).days)] += open_
    return out


def _account(name, root):
    a = row("Account", name, "name", "root_type", "disabled")
    if not a or a["disabled"]:
        throw(f"Account {name!r} does not exist or is disabled.")
    if a["root_type"] != root:
        throw(f"Account {name} must be a {root} account.")


class ExpectedCreditLossAssessment(Document):
    def validate(self):
        if self.docstatus == 0:
            self._calculate()
        validate_approval_transition(self)

    def _calculate(self):
        _account(self.expense_account, "Expense")
        _account(self.allowance_account, "Asset")
        exposure = receivable_exposure(self.assessment_date)
        rates = {b.bucket: D(b.loss_rate) for b in (self.bands or [])}
        for b, r in rates.items():
            if r < 0 or r > 100:
                throw(f"Loss rate for {b} must be between 0 and 100 percent.")
        self.set("bands", [])
        required = total = Decimal(0)
        for b in BUCKETS:
            loss = (exposure[b] * rates.get(b, Decimal(0)) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
            self.append("bands", {"bucket": b, "loss_rate": rates.get(b, Decimal(0)), "exposure": exposure[b], "expected_loss": loss})
            required += loss
            total += exposure[b]
        self.total_exposure, self.required_allowance = total, required
        self.existing_allowance = -D(get_account_balance(self.allowance_account))      # a credit balance is a positive allowance
        self.adjustment = required - D(self.existing_allowance)
        if self.adjustment == 0:
            throw("The allowance already equals the expected credit loss; there is nothing to post.")

    def before_submit(self):
        ensure_approved(self, required=True)
        exposure = receivable_exposure(self.assessment_date)
        required = sum(((exposure[b.bucket] * D(b.loss_rate) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP) for b in self.bands), Decimal(0))
        if required != D(self.required_allowance) or -D(get_account_balance(self.allowance_account)) != D(self.existing_allowance):
            throw("Receivables or the allowance changed after this assessment was calculated. Save it again to recalculate, then submit.")

    def on_submit(self):
        s = finance_settings()
        amount = abs(D(self.adjustment))
        charge = D(self.adjustment) > 0
        lines = [{"account": self.expense_account if charge else self.allowance_account, "debit": amount, "credit": 0, "line_description": "Expected credit loss"},
                 {"account": self.allowance_account if charge else self.expense_account, "debit": 0, "credit": amount, "line_description": "Expected credit loss"}]
        b = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.assessment_date, currency=(s["base_currency"] or "").upper(), exchange_rate=1, lines=lines,
                                       posting_event="Original", remarks=self.narration or f"Expected credit loss assessment {self.name}", idempotency_key=f"ecl:{self.name}")
        db_update(self, posting_batch=b.name, status="Posted")

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted assessment cannot be deleted; cancel it instead.")


def on_cancelled(doc, report):
    db_update(doc, status="Cancelled")
