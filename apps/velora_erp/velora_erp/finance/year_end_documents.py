from __future__ import annotations
from datetime import date
from decimal import Decimal
import hashlib, json
from sqlalchemy import select, func
from velora import Document, db, get_doc, get_list, throw
from velora.db.tables import get_table
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, approval_required
from .year_end import build_year_end_closing_proposal, YearEndCloseError

CHECKLIST = [
 ("BANK", "All bank and cash accounts are reconciled and supported."),
 ("AR_AP", "Receivables and payables subledgers agree to their control accounts."),
 ("INVENTORY", "Inventory quantities and valuation are reconciled."),
 ("ASSETS", "Fixed asset cost, depreciation, impairment and disposals are reconciled."),
 ("PAYROLL_TAX", "Payroll, PAYE, pension and statutory liabilities are reconciled."),
 ("TAX", "Current and deferred tax balances and disclosures are reviewed."),
 ("ACCRUALS", "Accruals, prepayments and cut-off adjustments are complete."),
 ("DISCLOSURES", "Financial statements and supporting notes are reconciled and approved."),
 ("SUSPENSE", "Suspense, clearing and control accounts have no unexplained balances."),
]

def _periods(financial_year):
 return sorted(get_list("Financial Period",filters=[["financial_year","=",financial_year]],
  fields=["name","period_number","start_date","end_date","status"],limit=1000,ignore_permissions=True),
  key=lambda x:(str(x.get("start_date")),int(x.get("period_number") or 0)))

def _period_balances(start_date,end_date):
 ledger=get_table("Account Ledger Record"); accounts=get_table("Account")
 query=(select(accounts.c.name,accounts.c.account_name,accounts.c.root_type,
  (func.coalesce(func.sum(ledger.c.base_debit),0)-func.coalesce(func.sum(ledger.c.base_credit),0)).label("balance"))
  .select_from(ledger.join(accounts,ledger.c.account==accounts.c.name))
  .where(ledger.c.posting_date>=start_date).where(ledger.c.posting_date<=end_date)
  .where(accounts.c.root_type.in_(["Income","Expense"]))
  .group_by(accounts.c.name,accounts.c.account_name,accounts.c.root_type)
  .order_by(accounts.c.name))
 with db.transaction() as conn: rows=[dict(x) for x in conn.execute(query).mappings()]
 return [{"account":x["name"],"account_type":x["root_type"],"balance":str(x["balance"])} for x in rows if Decimal(str(x["balance"] or 0))!=0]

def _automated_year_end_controls(financial_year):
 fy=get_doc("Financial Year",financial_year,ignore_permissions=True)
 ledger=get_table("Account Ledger Record")
 with db.transaction() as conn:
  totals=conn.execute(select(func.coalesce(func.sum(ledger.c.base_debit),0),
      func.coalesce(func.sum(ledger.c.base_credit),0)).where(ledger.c.posting_date<=fy.end_date)).first()
  rows=conn.execute(select(ledger.c.name,ledger.c.posting_date,ledger.c.account,ledger.c.base_debit,
      ledger.c.base_credit,ledger.c.posting_batch,ledger.c.posting_line,ledger.c.source_doctype,
      ledger.c.source_name).where(ledger.c.posting_date>=fy.start_date).where(ledger.c.posting_date<=fy.end_date)
      .order_by(ledger.c.posting_date,ledger.c.name)).mappings().all()
 difference=abs(Decimal(str(totals[0] or 0))-Decimal(str(totals[1] or 0)))
 pending=get_list("Deferred Tax Posting Inbox",filters=[["posting_date",">=",fy.start_date],
      ["posting_date","<=",fy.end_date],["status","in",["Pending Review","Approved"]]],
      fields=["name"],limit=10000,ignore_permissions=True)
 source=[{k:(str(v) if v is not None else None) for k,v in dict(x).items()} for x in rows]
 fingerprint=hashlib.sha256(json.dumps(source,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
 return difference,len(pending),fingerprint


def _validate_period_state(financial_year, posting_date):
 fy=get_doc("Financial Year",financial_year,ignore_permissions=True)
 if fy.status!="Open": throw("Only an Open Financial Year can enter the Year End Close workflow.")
 periods=_periods(financial_year)
 if not periods: throw("Create Financial Periods before starting year-end close.")
 if str(periods[0]["start_date"])!=str(fy.start_date) or str(periods[-1]["end_date"])!=str(fy.end_date):
  throw("Financial Periods must cover the complete Financial Year before year-end close.")
 for previous,current in zip(periods,periods[1:]):
  if (date.fromisoformat(str(previous["end_date"]))-date.fromisoformat(str(current["start_date"]))).days!=-1:
   throw("Financial Periods must be contiguous without gaps or overlaps before year-end close.")
 if any(x["status"]!="Closed" for x in periods[:-1]):
  throw("All Financial Periods except the final period must already be closed through approved Period Close documents.")
 if periods[-1]["status"]!="Open": throw("The final Financial Period must remain Open for the approved closing journal.")
 if str(posting_date)!=str(periods[-1]["end_date"]):
  throw("The closing journal date must equal the final Financial Period end date.")
 return fy,periods


def _proposal_snapshot(doc):
 fy=get_doc("Financial Year",doc.financial_year,ignore_permissions=True)
 settings=get_list("Finance Settings",fields=["base_currency"],limit=1,ignore_permissions=True)
 if not settings or not settings[0].get("base_currency"):
  throw("Finance Settings must contain the company base currency before year-end closing.")
 balances=_period_balances(fy.start_date,fy.end_date)
 try:
  proposal=build_year_end_closing_proposal(balances=balances,retained_earnings_account=doc.retained_earnings_account,
   posting_date=str(doc.posting_date),financial_year=doc.financial_year,currency=settings[0]["base_currency"])
 except YearEndCloseError as exc: throw(str(exc))
 return proposal

def _canonical_proposal(proposal):
 return {"status":proposal["status"],"posting_date":proposal["posting_date"],"financial_year":proposal["financial_year"],
  "currency":proposal["currency"],"retained_earnings_account":proposal["retained_earnings_account"],
  "lines":[{"account":x["account"],"account_type":x["account_type"],"debit":str(x["debit"]),"credit":str(x["credit"]),"description":x["description"]} for x in proposal["lines"]],
  "total_debit":str(proposal["total_debit"]),"total_credit":str(proposal["total_credit"]),"net_profit":str(proposal["net_profit"]),"fingerprint":proposal["fingerprint"]}

class YearEndClose(Document):
 def before_insert(self):
  if not self.checklist:
   for code,description in CHECKLIST:
    self.append("checklist",{"item_code":code,"description":description,"completed":0})
 def validate(self):
  validate_approval_transition(self)
  if not all((self.financial_year,self.posting_date,self.retained_earnings_account)):
   throw("Financial Year, Closing Journal Date and Retained Earnings Account are required.")
  fy,periods=_validate_period_state(self.financial_year,self.posting_date)
  account=get_doc("Account",self.retained_earnings_account,ignore_permissions=True)
  if account.disabled or account.root_type!="Equity": throw("Retained Earnings Account must be an active Equity ledger account.")
  duplicate=get_list("Year End Close",filters=[["financial_year","=",self.financial_year],["docstatus","=",1]],fields=["name"],limit=5,ignore_permissions=True)
  if duplicate and duplicate[0]["name"]!=self.name: throw(f"Financial Year {self.financial_year} already has a submitted Year End Close.")
  expected={x[0]:x[1] for x in CHECKLIST}; codes=[x.item_code for x in self.checklist]
  if set(codes)!=set(expected) or len(codes)!=len(expected): throw("Year End Close checklist has missing, duplicate or unsupported control items.")
  for item in self.checklist:
   if item.description!=expected[item.item_code]: throw(f"Checklist description for {item.item_code} is system-controlled.")
  proposal=_proposal_snapshot(self)
  canonical=_canonical_proposal(proposal)
  self.currency=proposal["currency"]; self.net_profit=proposal["net_profit"]
  self.total_debit=proposal["total_debit"]; self.total_credit=proposal["total_credit"]
  self.proposal_fingerprint=proposal["fingerprint"]
  self.proposal_snapshot=canonical
  tb_difference,pending_deferred,ledger_fingerprint=_automated_year_end_controls(self.financial_year)
  self.trial_balance_difference=tb_difference
  self.unresolved_deferred_tax_proposals=pending_deferred
  self.source_ledger_fingerprint=ledger_fingerprint
  self.system_checks_passed=int(tb_difference==0 and pending_deferred==0)
  if self.approval_status=="Approved" and not self.system_checks_passed:
   throw("Year End Close cannot be approved until the trial balance is balanced and all deferred tax proposals are resolved.")
  snapshot={"proposal":proposal["fingerprint"],"source_ledger_fingerprint":ledger_fingerprint,
   "trial_balance_difference":str(tb_difference),"unresolved_deferred_tax_proposals":pending_deferred,
   "financial_year":self.financial_year,"posting_date":str(self.posting_date),
   "retained_earnings_account":self.retained_earnings_account,"checklist":[{"code":x.item_code,"completed":bool(x.completed),
   "evidence":x.evidence_reference or "","notes":x.reviewer_notes or ""} for x in self.checklist],"close_notes":self.close_notes or ""}
  approval_hash=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(",",":")).encode()).hexdigest()
  old=getattr(self,"_old",None) or {}
  if approval_required(self.doctype) and old.get("approval_status")=="Approved" and self.approval_status=="Approved":
   if old.get("approval_hash")!=approval_hash or self.approval_hash!=approval_hash:
    throw("An approved Year End Close is immutable. Reset approval before changing source balances or review evidence.")
  elif self.approval_status=="Approved": self.approval_hash=approval_hash
  else: self.approval_hash=None
  self.status={"Pending":"Draft","Approved":"Approved","Rejected":"Rejected"}.get(self.approval_status,"Draft")
 def before_submit(self):
  ensure_approved(self,required=True)
  _validate_period_state(self.financial_year,self.posting_date)
  difference,pending,ledger_fingerprint=_automated_year_end_controls(self.financial_year)
  if difference!=0 or pending:
   throw("Year End Close automated controls failed: the trial balance must balance and all deferred tax proposals must be resolved.")
  if str(difference)!=str(self.trial_balance_difference) or pending!=int(self.unresolved_deferred_tax_proposals or 0) or ledger_fingerprint!=self.source_ledger_fingerprint:
   throw("The ledger or automated year-end controls changed after approval. Recalculate and obtain approval again.")
  incomplete=[x.item_code for x in self.checklist if not x.completed]
  if incomplete: throw("Complete every Year End Close review item before posting: "+", ".join(incomplete))
  missing=[x.item_code for x in self.checklist if not (x.evidence_reference or "").strip() or not (x.reviewer_notes or "").strip()]
  if missing: throw("Evidence references and reviewer notes are required for every Year End Close control: "+", ".join(missing))
  proposal=_proposal_snapshot(self)
  if proposal["fingerprint"]!=self.proposal_fingerprint:
   throw("The trial balance has changed since the Year End Close proposal was prepared. Recalculate and obtain approval again.")
 def on_submit(self):
  _validate_period_state(self.financial_year,self.posting_date)
  difference,pending,ledger_fingerprint=_automated_year_end_controls(self.financial_year)
  if difference!=0 or pending or ledger_fingerprint!=self.source_ledger_fingerprint:
   throw("The ledger changed immediately before Year End Close posting; the approved close is stale.")
  proposal=_proposal_snapshot(self)
  if proposal["fingerprint"]!=self.proposal_fingerprint: throw("The Year End Close source balances changed immediately before posting.")
  lines=[{"account":x["account"],"debit":x["debit"],"credit":x["credit"],"line_description":x["description"]} for x in proposal["lines"]]
  batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.posting_date,
   currency=self.currency,exchange_rate=1,lines=lines,posting_event="Original",remarks=f"Approved Year End Close {self.financial_year}",
   idempotency_key=f"year-end-close:{self.name}")
  periods=_periods(self.financial_year); final=get_doc("Financial Period",periods[-1]["name"],ignore_permissions=True)
  db_update(final,status="Closed",closed_on=self.posting_date,close_notes=f"Closed through approved Year End Close {self.name}")
  fy=get_doc("Financial Year",self.financial_year,ignore_permissions=True)
  db_update(fy,status="Closed",closing_date=self.posting_date,is_current=0)
  db_update(self,posting_batch=batch.name,status="Closed")
 def before_delete(self):
  if self.docstatus==1: throw("A submitted Year End Close is retained for audit.")
