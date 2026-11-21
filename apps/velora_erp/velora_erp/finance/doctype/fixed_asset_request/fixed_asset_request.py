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
    b = post_financial_transaction(source_doctype=doc.doctype, source_name=doc.name, posting_date=posting_date, currency=currency, exchange_rate=rate or 1, lines=lines, posting_event=event, remarks=remarks, idempotency_key=f"{doc.doctype.lower().replace(' ','-')}:{doc.name}:{event.lower()}")
    return _persist(doc,b)

class FixedAssetRequest(Document):
    def validate(self):
        _approval(self)
        if not self.purpose or not self.items: throw("Business Purpose and at least one requested asset are required.")
        total=Decimal("0")
        for i,l in enumerate(self.items,1):
            if int(l.quantity or 0)<=0 or D(l.estimated_unit_cost)<=0: throw(f"Request line {i}: quantity and estimated cost must be positive.")
            category=get_doc("Fixed Asset Category",l.asset_category,ignore_permissions=True)
            if category.disabled: throw(f"Request line {i}: asset category is disabled.")
            total+=D(l.quantity)*D(l.estimated_unit_cost)
        self.estimated_total=total
    def before_submit(self): _approved(self)
    def on_submit(self): self.status="Approved"; db_update(self, status="Approved")
