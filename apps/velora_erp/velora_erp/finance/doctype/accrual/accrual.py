from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from velora import Document, throw, get_doc, new_doc, get_list
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved
from velora_erp.finance.validation import row
from velora.permissions import get_session
from velora_erp.finance.doctype._utils import db_update

CENT = Decimal("0.01")
def D(v): return Decimal(str(v or 0))
def _approval(doc): validate_approval_transition(doc)
def _approved(doc): ensure_approved(doc, required=True)
def _persist(doc, batch):
    doc.posting_batch = batch.name
    db_update(doc, posting_batch=batch.name)
    return batch
def _account(name, roots=None):
    a = row("Account", name, "name", "root_type", "account_type", "disabled", "account_currency")
    if not a or a["disabled"]: throw(f"Account {name!r} does not exist or is disabled.")
    if roots and a["root_type"] not in roots: throw(f"Account {name} must be a {', '.join(roots)} account.")
    return a
def _safe_post(doc, posting_date, currency, rate, lines, event, remarks):
    b = post_financial_transaction(source_doctype=doc.doctype, source_name=doc.name, posting_date=posting_date, currency=currency, exchange_rate=rate or 1, lines=lines, posting_event="Original", remarks=remarks, idempotency_key=f"{doc.doctype.lower().replace(' ','-')}:{doc.name}:{event.lower()}")
    return _persist(doc,b)

class Accrual(Document):
    def validate(self):
        _approval(self)
        if not self.reporting_date or not self.description or not self.lines: throw("Accrual Date, Description and at least one line are required.")
        if not self.currency or len(str(self.currency))!=3 or not str(self.currency).isalpha(): throw("Accrual Currency must be a three-letter ISO currency code.")
        if D(self.exchange_rate)<=0: throw("Accrual Exchange Rate must be greater than zero.")
        total=Decimal("0")
        for i,l in enumerate(self.lines,1):
            amount=D(l.amount)
            if amount<=0: throw(f"Accrual line {i}: amount must be greater than zero.")
            _account(l.expense_account,["Expense"]); _account(l.accrued_liability_account,["Liability"])
            total+=amount
        self.total_accrual=total
        if self.auto_reverse and not self.reversal_date: throw("Reversal Date is required when Automatically Reverse is selected.")
        if self.auto_reverse and str(self.reversal_date)<=str(self.reporting_date): throw("Reversal Date must be after Accrual Date.")
    def before_submit(self): _approved(self)
    def on_submit(self):
        lines=[]
        for l in self.lines:
            common={"cost_centre":l.cost_centre or None,"business_unit":l.business_unit or None,"dimensions":l.dimensions or {},"party_type":l.party_type or None,"party":l.party or None,"line_description":l.description}
            lines += [{"account":l.expense_account,"debit":l.amount,"credit":0,**common},{"account":l.accrued_liability_account,"debit":0,"credit":l.amount,**common}]
        b=_safe_post(self,self.reporting_date,self.currency,self.exchange_rate,lines,"Accrual",self.description)
        self.status="Posted"; db_update(self, status="Posted")
    def before_delete(self):
        if self.docstatus==1: throw("A submitted accrual cannot be deleted.")

def _post_auto_reversal(doc):
    """The accrual's own next-period entry (an accounting convention, not an undo): the same lines the other way round, dated Reversal Date."""
    original=get_doc("Financial Posting Batch",doc.posting_batch,ignore_permissions=True)
    keep=("account","party_type","party","cost_centre","dimensions","item","warehouse","asset","project","business_unit","branch")
    lines=[{**{k:getattr(l,k) for k in keep},"debit":l.credit,"credit":l.debit,"base_debit":l.base_credit,"base_credit":l.base_debit,
            "line_description":f"Automatic reversal of accrual {doc.name}"} for l in original.lines]
    return post_financial_transaction(source_doctype=doc.doctype,source_name=doc.name,posting_date=doc.reversal_date,currency=original.currency,
        exchange_rate=original.exchange_rate,lines=lines,posting_event="Adjustment",remarks=f"Automatic accrual reversal: {doc.name}",
        idempotency_key=f"accrual-reversal:{doc.name}")

def process_due_accrual_reversals(as_of_date=None):
    as_of_date=as_of_date or date.today()
    rows=get_list("Accrual",filters={"docstatus":1,"auto_reverse":1},fields=["name","reversal_date","reversal_batch"],limit=10000,ignore_permissions=True)
    done=[]
    for r in rows:
        if not r.get("reversal_date") or r.get("reversal_batch") or str(r["reversal_date"])>str(as_of_date): continue
        doc=get_doc("Accrual",r["name"],ignore_permissions=True)
        batch=_post_auto_reversal(doc)
        db_update(doc, reversal_batch=batch.name, status="Reversed"); done.append(doc.name)
    return done
