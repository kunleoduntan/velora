from decimal import Decimal, ROUND_HALF_UP
import csv, hashlib, io
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

def _parse_csv(doc):
    raw=(doc.raw_csv_data or "").strip()
    if not raw: return
    if doc.transactions: throw("Use either pasted CSV data or manually entered statement lines, not both.")
    reader=csv.DictReader(io.StringIO(raw))
    required={"transaction_date","direction","description","bank_reference","amount","offset_account"}
    headers=set(reader.fieldnames or [])
    missing=required-headers
    if missing: throw("CSV is missing required headers: "+", ".join(sorted(missing)))
    count=0
    for row_data in reader:
        if not any((v or "").strip() for v in row_data.values()): continue
        values={key:(row_data.get(key) or "").strip() or None for key in (
            "transaction_date","direction","description","bank_reference","amount","offset_account","party_type","party","cost_centre","business_unit")}
        try: values["transaction_date"]=date.fromisoformat(values["transaction_date"])
        except (TypeError,ValueError): throw(f"CSV row {count+1}: Transaction Date must use YYYY-MM-DD.")
        doc.append("transactions", values)
        count+=1
    if not count: throw("The CSV contains no statement rows.")
    doc.import_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest()
    doc.raw_csv_data=None
    doc._link_children()

def _apply_coding_rules(doc):
    rules=get_list("Bank Transaction Coding Rule",filters={"disabled":0},fields=["name","priority","match_field","match_operator","match_text","direction","offset_account","party_type","party","cost_centre","business_unit","valid_from","valid_to"],limit=10000,ignore_permissions=True)
    rules.sort(key=lambda r:(int(r.get("priority") or 100),r["name"]))
    for line in doc.transactions:
        if line.offset_account: continue
        matches=[]
        for rule in rules:
            if rule.get("direction") and rule["direction"]!=line.direction: continue
            if rule.get("valid_from") and str(line.transaction_date)<str(rule["valid_from"]): continue
            if rule.get("valid_to") and str(line.transaction_date)>str(rule["valid_to"]): continue
            source=(line.description if rule["match_field"]=="Description" else (line.bank_reference or "")) or ""
            source=source.casefold(); target=rule["match_text"].casefold()
            op=rule["match_operator"]
            matched=(target in source) if op=="Contains" else source.startswith(target) if op=="Starts With" else source==target
            if matched: matches.append(rule)
        if matches:
            top_priority=matches[0]["priority"]
            top=[r for r in matches if r["priority"]==top_priority]
            accounts={r["offset_account"] for r in top}
            if len(accounts)>1:
                line.processing_status="Exception"; line.exception_reason="Conflicting coding rules at the same priority. Resolve manually."; continue
            rule=matches[0]
            line.offset_account=rule["offset_account"]; line.party_type=rule.get("party_type"); line.party=rule.get("party")
            line.cost_centre=rule.get("cost_centre"); line.business_unit=rule.get("business_unit")
    
class BankTransactionProcessor(Document):
    def validate(self):
        _parse_csv(self)
        if not self.transactions: throw("At least one imported statement line is required.")
        _apply_coding_rules(self)
        if not self.bank_account or not self.import_reference or not self.transactions: throw("Bank Account, Import Reference and statement lines are required.")
        bank=_account(self.bank_account,["Asset"])
        if bank.get("account_type") not in ("BANK","CASH"): throw("Bank GL Account must be configured as Bank or Cash.")
        if self.statement_date_from and self.statement_date_to and str(self.statement_date_to)<str(self.statement_date_from): throw("Statement To cannot be earlier than Statement From.")
        duplicate_refs=set(); receipts=payments=0; exceptions=0
        for i,l in enumerate(self.transactions,1):
            if D(l.amount)<=0: throw(f"Statement line {i}: Amount must be greater than zero.")
            ref=str(l.bank_reference or "").strip()
            if ref and ref in duplicate_refs: throw(f"Statement line {i}: duplicate bank reference {ref} in this import.")
            if ref: duplicate_refs.add(ref)
            if l.offset_account:
                _account(l.offset_account)
                if l.processing_status != "Exception": l.processing_status="Coded"
            else:
                l.processing_status="Exception"
                if not l.exception_reason: l.exception_reason="Offset Account is required before batch creation."
                exceptions+=1
            if l.processing_status == "Exception" and l.offset_account: exceptions+=1
            if self.statement_date_from and str(l.transaction_date)<str(self.statement_date_from): throw(f"Statement line {i}: date is before Statement From.")
            if self.statement_date_to and str(l.transaction_date)>str(self.statement_date_to): throw(f"Statement line {i}: date is after Statement To.")
            if l.direction=="Receipt": receipts+=D(l.amount)
            elif l.direction=="Payment": payments+=D(l.amount)
            else: throw(f"Statement line {i}: Direction must be Receipt or Payment.")
        self.total_receipts=receipts; self.total_payments=payments; self.exception_count=exceptions
        if D(self.exchange_rate)<=0: throw("Exchange Rate must be greater than zero.")
        if exceptions: self.status="Draft"
    def before_submit(self):
        if any(l.processing_status != "Coded" or not l.offset_account for l in self.transactions): throw("Resolve every coding exception before creating a Bank Batch.")
    def on_submit(self):
        batch=new_doc("Batch Bank Transaction",bank_account=self.bank_account,posting_date=self.statement_date_to or max(str(l.transaction_date) for l in self.transactions),currency=self.currency,exchange_rate=self.exchange_rate,reference=self.import_reference,approval_status="Pending",transactions=[{"transaction_date":l.transaction_date,"direction":l.direction,"description":l.description,"offset_account":l.offset_account,"party_type":l.party_type,"party":l.party,"amount":l.amount,"reference":l.bank_reference,"cost_centre":l.cost_centre,"business_unit":l.business_unit,"dimensions":l.dimensions} for l in self.transactions])
        batch.insert(ignore_permissions=True)
        self.generated_batch=batch.name; self.status="Batch Created"; db_update(self, generated_batch=batch.name, status="Batch Created")
    def before_delete(self):
        if self.docstatus==1: throw("A submitted bank processor cannot be deleted.")
