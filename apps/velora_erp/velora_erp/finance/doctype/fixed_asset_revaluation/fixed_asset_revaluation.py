from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from velora import Document, throw, get_doc, new_doc, get_list
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.validation import row
from velora.permissions import get_session
from velora_erp.finance.doctype._utils import db_update

CENT = Decimal("0.01")
def _base_currency(): return finance_settings()["base_currency"]
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

class FixedAssetRevaluation(Document):
    def validate(self):
        _approval(self)
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True)
        if asset.status not in ("Active","Leased"): throw("Only an active asset can be revalued.")
        if self.docstatus==0:
            from velora_erp.finance.asset_rules import require_depreciation_up_to
            require_depreciation_up_to(asset,self.revaluation_date,"revaluation")
        if asset.components: throw("This asset uses component accounting. Revalue its significant components individually before applying a component-level revaluation release.")
        self.previous_carrying_amount=asset.carrying_amount
        delta=D(self.new_carrying_amount)-D(asset.carrying_amount); self.movement=delta
        if D(self.new_carrying_amount)<=0: throw("New Carrying Amount must be greater than zero.")
        if delta==0: throw("New Carrying Amount must differ from the current carrying amount.")
        if str(self.revaluation_date)<str(asset.acquisition_date): throw("Revaluation Date cannot be before Acquisition Date.")
        if delta>0:
            gain_reversal=min(delta,D(asset.revaluation_loss_balance))
            if gain_reversal>0: _account(self.revaluation_gain_account,["Income"])
            if delta>gain_reversal: _account(self.revaluation_surplus_account,["Equity"])
        elif delta<0:
            reserve_release=min(-delta,D(asset.revaluation_surplus))
            if reserve_release>0: _account(self.revaluation_surplus_account,["Equity"])
            if -delta>reserve_release: _account(self.revaluation_loss_account,["Expense"])
        if self.valuation_method=="Professional Valuation" and (not self.appraiser or not self.valuation_reference): throw("Professional Valuation requires the appraiser and valuation report reference.")
        if not self.reason: throw("Revaluation reason is required.")
    def before_submit(self): _approved(self)
    def on_submit(self):
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True); delta=D(self.movement); lines=[]
        if delta>0:
            gain_reversal=min(delta,D(asset.revaluation_loss_balance)); surplus=delta-gain_reversal
            lines=[{"account":asset.asset_account,"debit":delta,"credit":0,"asset":asset.name,"line_description":f"Revaluation increase {asset.name}"}]
            if gain_reversal>0: lines.append({"account":self.revaluation_gain_account,"debit":0,"credit":gain_reversal,"asset":asset.name,"line_description":f"Reversal of prior revaluation loss {asset.name}"})
            if surplus>0: lines.append({"account":self.revaluation_surplus_account,"debit":0,"credit":surplus,"asset":asset.name,"line_description":f"Revaluation surplus {asset.name}"})
            asset.revaluation_loss_balance=D(asset.revaluation_loss_balance)-gain_reversal
            asset.revaluation_surplus=D(asset.revaluation_surplus)+surplus
            asset.revaluation_adjustment=D(asset.revaluation_adjustment)+delta
        elif delta<0:
            amount=-delta
            reserve_release=min(amount,D(asset.revaluation_surplus))
            loss=amount-reserve_release
            if reserve_release>0:
                if not self.revaluation_surplus_account: throw("Revaluation Surplus Account is required to release an existing asset revaluation reserve.")
                lines.append({"account":self.revaluation_surplus_account,"debit":reserve_release,"credit":0,"asset":asset.name,"line_description":f"Release revaluation surplus {asset.name}"})
                asset.revaluation_surplus=D(asset.revaluation_surplus)-reserve_release
            if loss>0:
                lines.append({"account":self.revaluation_loss_account,"debit":loss,"credit":0,"asset":asset.name,"line_description":f"Revaluation loss {asset.name}"})
            lines.append({"account":asset.asset_account,"debit":0,"credit":amount,"asset":asset.name,"line_description":f"Asset revaluation decrease {asset.name}"})
            asset.revaluation_loss_balance=D(asset.revaluation_loss_balance)+loss
            asset.revaluation_adjustment=D(asset.revaluation_adjustment)+delta
        else: throw("Revaluation has no financial movement.")
        b=_safe_post(self,self.revaluation_date,_base_currency(),1,lines,"Asset Revaluation",self.reason)
        from velora_erp.finance.doctype._utils import db_update
        previous_carrying=D(self.previous_carrying_amount)
        db_update(asset, carrying_amount=self.new_carrying_amount, revaluation_adjustment=asset.revaluation_adjustment,
                  revaluation_surplus=asset.revaluation_surplus, revaluation_loss_balance=asset.revaluation_loss_balance,
                  impairment_ceiling_carrying_amount=(D(asset.impairment_ceiling_carrying_amount)+delta if D(asset.impairment_ceiling_carrying_amount)>0 else asset.impairment_ceiling_carrying_amount))
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(asset, "Revaluation", self.revaluation_date, self.doctype, self.name,
            from_values={"carrying_amount": str(previous_carrying)},
            to_values={"carrying_amount": str(self.new_carrying_amount), "movement": str(delta)}, reason=self.reason)
