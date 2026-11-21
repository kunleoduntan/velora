from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from velora import Document, throw, get_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required, finance_settings
from velora_erp.finance.validation import row
from velora_erp.finance.doctype._utils import db_update

CENT=Decimal("0.01")
def D(v): return Decimal(str(v if v not in (None, "") else 0))
def M(v): return D(v).quantize(CENT,rounding=ROUND_HALF_UP)

class DeferredTaxPostingInbox(Document):
    def validate(self):
        old=getattr(self,"_old",None) or {}
        if old.get("status")=="Superseded":
            throw("A superseded deferred tax proposal is retained for audit and cannot be reopened.")
        validate_approval_transition(self)
        if not self.source_assessment or not self.posting_date or not self.lines:
            throw("Source assessment, posting date and proposed journal lines are required.")
        assessment=get_doc("Deferred Tax Assessment",self.source_assessment,ignore_permissions=True)
        if str(assessment.assessment_date)!=str(self.posting_date):
            throw("Posting proposal must match its source assessment date.")
        if assessment.posting_inbox and assessment.posting_inbox!=self.name:
            throw("This proposal is not the active inbox item linked to its source assessment.")
        if self.approval_status=="Approved": self.status="Approved"
        elif self.approval_status=="Rejected": self.status="Rejected"
        else: self.status="Pending Review"
        debit=credit=Decimal("0")
        for i,line in enumerate(self.lines,1):
            a=row("Account",line.account,"name","disabled","root_type")
            expected={"Deferred Tax Asset":"Asset","Deferred Tax Liability":"Liability","Deferred Tax Expense":"Expense","Deferred Tax Benefit":"Income"}.get(line.entry_type)
            if not a or a["disabled"]: throw(f"Line {i}: account must exist and be active.")
            if not expected or a["root_type"]!=expected:
                throw(f"Line {i}: {line.entry_type} must use an active {expected or 'valid'} account.")
            d,c=M(line.debit),M(line.credit)
            if (d>0)==(c>0): throw(f"Line {i}: enter either a debit or credit amount, but not both.")
            debit+=d; credit+=c
        if debit<=0 or debit!=credit: throw("Deferred tax posting proposal must contain balanced, non-zero debit and credit totals.")
        self.total_debit=M(debit); self.total_credit=M(credit)
        snapshot={"source_assessment":self.source_assessment,"posting_date":str(self.posting_date),"currency":self.currency,"exchange_rate":str(self.exchange_rate or 1),"remarks":self.remarks or "","lines":[{"entry_type":r.entry_type,"account":r.account,"debit":str(M(r.debit)),"credit":str(M(r.credit)),"line_description":r.line_description or ""} for r in self.lines]}
        current_hash=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        old_status=old.get("approval_status")
        if approval_required(self.doctype) and old_status=="Approved" and self.approval_status=="Approved":
            if self.approval_hash!=old.get("approval_hash") or self.approval_hash!=current_hash:
                throw("An approved deferred tax proposal is immutable. Reset approval to Pending through an authorised manager before making corrections.")
        elif self.approval_status=="Approved":
            self.approval_hash=current_hash
        else:
            self.approval_hash=None
        if self.docstatus==1 or self.posting_batch:
            throw("A posted deferred tax proposal is immutable.")
    def on_update(self):
        if self.source_assessment and self.approval_status in ("Approved","Rejected"):
            assessment=get_doc("Deferred Tax Assessment",self.source_assessment,ignore_permissions=True)
            db_update(assessment,status=self.approval_status)
    def before_submit(self):
        if self.status!="Approved":
            throw("Only an approved, current deferred tax proposal can be posted. Superseded or rejected proposals cannot be submitted.")
        ensure_approved(self,required=True)
        if self.posting_batch: throw("This deferred tax proposal has already been posted.")
    def on_submit(self):
        settings=finance_settings()
        lines=[{"account":r.account,"debit":M(r.debit),"credit":M(r.credit),"line_description":r.line_description or r.entry_type or "Deferred tax movement"} for r in self.lines]
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.posting_date,currency=self.currency or settings["base_currency"],exchange_rate=self.exchange_rate or 1,lines=lines,posting_event="Original",remarks=self.remarks or f"Deferred tax posting proposal {self.name}",idempotency_key=f"deferred-tax-inbox:{self.name}")
        db_update(self,posting_batch=batch.name,status="Posted")
        assessment=get_doc("Deferred Tax Assessment",self.source_assessment,ignore_permissions=True)
        db_update(assessment,status="Posted")
def before_delete(self):
        throw("Deferred tax posting inbox records are retained for audit, including rejected proposals.")
