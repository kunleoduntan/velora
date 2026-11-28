from datetime import date, timedelta
from decimal import Decimal

from velora import Document, get_doc, get_list, throw
from velora_erp.finance import revaluation as rv
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import ensure_approved, finance_settings, validate_approval_transition

D = lambda v: Decimal(str(v or 0))


def _accounts():
    s = finance_settings()
    gain, loss = s.get("unrealised_exchange_gain_account"), s.get("unrealised_exchange_loss_account")
    if not gain or not loss:
        throw("Choose the unrealised exchange gain and loss accounts in Finance Settings (Foreign Exchange Accounts) before revaluing.")
    return s, gain, loss


class ForeignCurrencyRevaluation(Document):
    def validate(self):
        if self.docstatus == 0:
            self._calculate()
        if self.auto_reverse:
            self.reversal_date = self.reversal_date or (self.revaluation_date + timedelta(days=1) if isinstance(self.revaluation_date, date) else None)
            if self.reversal_date and str(self.reversal_date) <= str(self.revaluation_date):
                throw("The reversal date must be after the revaluation date.")
        validate_approval_transition(self)

    def _calculate(self):
        s = finance_settings()
        rows = rv.revaluation_rows(self.revaluation_date, (s["base_currency"] or "").upper(), int(s.get("decimal_places") if s.get("decimal_places") is not None else 2))
        self.set("lines", [])
        for r in rows:
            self.append("lines", r)
        self.total_gain = sum((D(r["difference"]) for r in rows if D(r["difference"]) > 0), Decimal(0))
        self.total_loss = -sum((D(r["difference"]) for r in rows if D(r["difference"]) < 0), Decimal(0))
        self.net_effect = D(self.total_gain) - D(self.total_loss)
        if not rows:
            throw("Nothing needs revaluing: every foreign-currency balance already stands at the closing rate.")

    def before_submit(self):
        ensure_approved(self, required=True)
        s = finance_settings()
        fresh = rv.revaluation_rows(self.revaluation_date, (s["base_currency"] or "").upper(), int(s.get("decimal_places") if s.get("decimal_places") is not None else 2))
        if sorted((r["account"], r["party"] or "", r["currency"], str(r["difference"])) for r in fresh) != sorted((l.account, l.party or "", l.currency, str(D(l.difference))) for l in self.lines):
            throw("The ledger or the exchange rates changed after this revaluation was calculated. Save it again to recalculate, then submit.")

    def on_submit(self):
        s, gain, loss = _accounts()
        per_ccy = rv.posting_lines_by_currency(self, gain, loss)
        first = None
        for ccy, lines in sorted(per_ccy.items()):
            rate = next(l.closing_rate for l in self.lines if l.currency == ccy)
            batch = post_financial_transaction(source_doctype=self.doctype, source_name=self.name, posting_date=self.revaluation_date, currency=ccy, exchange_rate=rate, lines=lines,
                                               posting_event="Original", remarks=self.narration or f"Foreign currency revaluation {self.name}", idempotency_key=f"fx-revaluation:{self.name}:{ccy}", source_part=ccy)
            first = first or batch.name
        db_update(self, posting_batch=first, status="Posted")

    def before_delete(self):
        if self.docstatus == 1:
            throw("A submitted revaluation cannot be deleted; cancel it instead.")


def _reverse(doc):
    """The next-period reversal of an unrealised difference: the same lines the other way round (a convention, not an undo)."""
    s, gain, loss = _accounts()
    first = None
    for ccy, lines in sorted(rv.posting_lines_by_currency(doc, gain, loss).items()):
        flipped = [{**l, "base_debit": l.get("base_credit", 0), "base_credit": l.get("base_debit", 0), "line_description": f"Reversal of revaluation {doc.name}"} for l in lines]
        for l in flipped:
            if not l["base_debit"]: l.pop("base_debit")
            if not l["base_credit"]: l.pop("base_credit")
        rate = next(x.closing_rate for x in doc.lines if x.currency == ccy)
        b = post_financial_transaction(source_doctype=doc.doctype, source_name=doc.name, posting_date=doc.reversal_date, currency=ccy, exchange_rate=rate, lines=flipped,
                                       posting_event="Adjustment", remarks=f"Reversal of revaluation {doc.name}", idempotency_key=f"fx-revaluation-reversal:{doc.name}:{ccy}", source_part=ccy)
        first = first or b.name
    return first


def process_due_reversals(as_of_date=None):
    as_of_date = as_of_date or date.today()
    done = []
    for r in get_list("Foreign Currency Revaluation", filters={"docstatus": 1, "auto_reverse": 1}, fields=["name", "reversal_date", "reversal_batch"], limit=5000, ignore_permissions=True):
        if not r.get("reversal_date") or r.get("reversal_batch") or str(r["reversal_date"]) > str(as_of_date):
            continue
        doc = get_doc("Foreign Currency Revaluation", r["name"], ignore_permissions=True)
        db_update(doc, reversal_batch=_reverse(doc), status="Reversed")
        done.append(doc.name)
    return done


def on_cancelled(doc, report):
    db_update(doc, status="Cancelled", reversal_batch=None)
