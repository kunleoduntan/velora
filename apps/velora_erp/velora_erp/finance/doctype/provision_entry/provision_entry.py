"""IAS 37 provisions. A provision is recognised only when all three criteria hold (37.14); it is measured at the best estimate,
unwound as the discount runs off, used only for the expenditure it was set up for (37.61) and released when no longer needed (37.59)."""
from decimal import Decimal

from velora import Document, throw
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import get_account_balance, post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, finance_settings, validate_approval_transition
from velora_erp.finance.validation import row

ADDS = ("Recognise", "Increase", "Unwind discount")


def D(v):
    return Decimal(str(v or 0))


def _account(name, roots, label):
    a = row("Account", name, "name", "root_type", "disabled")
    if not a or a["disabled"]:
        throw(f"{label} {name!r} does not exist or is disabled.")
    if roots and a["root_type"] not in roots:
        throw(f"{label} {name} must be a {' or '.join(roots)} account.")


class ProvisionEntry(Document):
    def validate(self):
        if D(self.amount) <= 0:
            throw("The amount must be greater than zero.")
        if self.provision_account == self.counter_account:
            throw("The provision account and the counter account must differ.")
        _account(self.provision_account, ["Liability"], "Provision account")
        _account(self.counter_account, None, "Counter account")
        if self.entry_type in ("Recognise", "Increase") and not (self.present_obligation and self.probable_outflow and self.reliable_estimate):
            throw("A provision is recognised only when there is a present obligation from a past event, an outflow is probable and the amount can be estimated reliably. Confirm all three, or do not provide.")
        if self.docstatus == 0:
            self.provision_balance = -D(get_account_balance(self.provision_account))
            if self.entry_type not in ADDS and D(self.amount) > D(self.provision_balance):
                throw(f"The provision holds {self.provision_balance}; {self.entry_type.lower()} of {self.amount} is more than it holds.")
        validate_approval_transition(self)

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        s = finance_settings()
        amount = D(self.amount)
        adds = self.entry_type in ADDS
        lines = [{"account": self.counter_account if adds else self.provision_account, "debit": amount, "credit": 0, "line_description": f"{self.entry_type}: {self.description}"},
                 {"account": self.provision_account if adds else self.counter_account, "debit": 0, "credit": amount, "line_description": f"{self.entry_type}: {self.description}"}]
        b = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.entry_date, currency=(s["base_currency"] or "").upper(), exchange_rate=1, lines=lines,
                                       posting_event="Original", remarks=self.narration or self.description, idempotency_key=f"provision:{self.name}")
        db_update(self, posting_batch=b.name, status="Posted")

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted provision entry cannot be deleted; cancel it instead.")


def on_cancelled(doc, report):
    db_update(doc, status="Cancelled")
