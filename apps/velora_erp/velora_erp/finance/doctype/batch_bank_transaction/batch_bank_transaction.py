from velora_erp.finance.multicurrency import base_currency
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

class BatchBankTransaction(Document):
    def validate(self):
        _approval(self)
        if not self.bank_account or not self.posting_date or not self.transactions: throw("Bank GL Account, Posting Date and transaction lines are required.")
        bank=_account(self.bank_account,["Asset"]);
        if bank.get("account_type") not in ("BANK","CASH"): throw("Bank GL Account must be configured as Bank or Cash.")
        receipts=payments=Decimal("0"); errors=[]; seen={}
        from sqlalchemy import select
        from velora import db
        from velora.db.tables import get_table
        parent,line_t=get_table("Batch Bank Transaction"),get_table("Bank Transaction Line")
        with db.transaction() as conn:
            prior=conn.execute(select(line_t.c.transaction_date,line_t.c.direction,line_t.c.amount,line_t.c.reference,parent.c.name)
                .select_from(line_t.join(parent,line_t.c.parent==parent.c.name))
                .where(parent.c.docstatus==1,parent.c.bank_account==self.bank_account,parent.c.name!=(self.name or ""))).mappings().all()
        existing={(str(r["transaction_date"])[:10],r["direction"],D(r["amount"]),(r["reference"] or "").strip().casefold()):r["name"] for r in prior}
        for i,l in enumerate(self.transactions,1):
            try:
                if l.direction not in ("Receipt","Payment"): throw("Direction must be Receipt or Payment.")
                amount=D(l.amount)
                if amount<=0: throw("Amount must be greater than zero.")
                _account(l.offset_account)
                if l.party_type and not l.party: throw("Party is required when Party Type is supplied.")
                ref=(l.reference or "").strip().casefold()
                if ref and not l.allow_duplicate:
                    key=(str(l.transaction_date)[:10],l.direction,amount,ref)
                    if key in seen: throw(f"Duplicate of line {seen[key]} in this batch (same date, direction, amount and reference).")
                    if key in existing: throw(f"Already posted in {existing[key]} (same bank, date, direction, amount and reference). Tick Allow Duplicate if this is genuinely a second transaction.")
                    seen[key]=i
                if l.direction=="Receipt": receipts+=amount
                else: payments+=amount
            except Exception as exc:
                errors.append(f"Line {i}: {exc}")
        if errors:
            more=f" (and {len(errors)-25} more)" if len(errors)>25 else ""
            throw("Fix these lines before saving: "+" | ".join(errors[:25])+more)
        self.total_receipts=receipts; self.total_payments=payments; self.net_movement=receipts-payments
        self.currency=(self.currency or bank.get("account_currency") or base_currency()).upper()
        if D(self.exchange_rate)<=0: throw("Exchange Rate must be greater than zero.")
    def before_submit(self): _approved(self)
    def on_submit(self):
        lines=[]
        for l in self.transactions:
            common={"party_type":l.party_type or None,"party":l.party or None,"cost_centre":l.cost_centre or None,"business_unit":l.business_unit or None,"dimensions":l.dimensions or {},"line_description":l.description,"transaction_date":l.transaction_date,"external_reference":l.reference or None}
            if l.direction=="Receipt": lines += [{"account":self.bank_account,"debit":l.amount,"credit":0,**common},{"account":l.offset_account,"debit":0,"credit":l.amount,**common}]
            else: lines += [{"account":l.offset_account,"debit":l.amount,"credit":0,**common},{"account":self.bank_account,"debit":0,"credit":l.amount,**common}]
        _safe_post(self,self.posting_date,self.currency,self.exchange_rate,lines,"Bank Movement",f"Bank batch {self.name}")
    def before_delete(self):
        if self.docstatus==1: throw("A posted bank batch cannot be deleted.")
