from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from velora import Document, throw, get_doc, new_doc, get_list
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.validation import row
from velora.permissions import get_session
from velora_erp.finance.doctype._utils import db_update, db_update_child

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

class FixedAssetDisposal(Document):
    def validate(self):
        _approval(self)
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True)
        if asset.status != "Active": throw("Only an owned active asset can be disposed. Right-of-use asset disposal is blocked because lease termination accounting is not yet supported.")
        self.carrying_amount=asset.carrying_amount
        if str(self.disposal_date)<str(asset.acquisition_date): throw("Disposal Date cannot be before Acquisition Date.")
        if D(self.disposal_proceeds)<0 or D(self.disposal_costs)<0: throw("Disposal Proceeds and Disposal Costs cannot be negative.")
        if D(self.disposal_proceeds)>0:
            if not self.proceeds_account: throw("Proceeds Account is required when proceeds are received.")
            _account(self.proceeds_account,["Asset"])
        if self.disposal_type=="Sale" and D(self.disposal_proceeds)>0 and not self.buyer: throw("Buyer / Recipient is required for an asset sale.")
        if self.disposal_type not in ("Theft / Loss",) and not self.physical_verification_done: throw("Physical verification must be completed before this disposal can be approved.")
        if self.physical_verification_done and (not self.verified_by or not self.verification_date): throw("Verified By and Verification Date are required when physical verification is completed.")
        if D(self.disposal_costs)>0:
            _account(self.disposal_cost_account,["Expense"]); _account(self.disposal_cost_payment_account,["Asset"])
            if D(self.disposal_costs)>D(self.disposal_proceeds): throw("Disposal Costs cannot exceed gross Disposal Proceeds.")
        self.net_disposal_proceeds=D(self.disposal_proceeds)-D(self.disposal_costs)
        self.asset_account=asset.asset_account; self.accumulated_depreciation_account=asset.accumulated_depreciation_account
        if D(asset.impairment_loss)>0:
            category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            self.impairment_account=self.impairment_account or asset.impairment_account or category.impairment_account
            _account(self.impairment_account,["Asset"])
        # The gain/loss posting is based on gross proceeds; disposal costs are
        # separately expensed. The displayed net gain/loss includes those costs.
        gross_gain_loss=D(self.disposal_proceeds)-D(asset.carrying_amount)
        self.gain_loss=D(self.net_disposal_proceeds)-D(asset.carrying_amount)
        if gross_gain_loss>0: _account(self.gain_account,["Income"])
        elif gross_gain_loss<0: _account(self.loss_account,["Expense"])
    def before_submit(self): _approved(self)
    def on_submit(self):
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True); cost=D(asset.acquisition_cost)+D(asset.revaluation_adjustment); accum=D(asset.accumulated_depreciation); impairment=D(asset.impairment_loss); proceeds=D(self.disposal_proceeds); carrying=D(asset.carrying_amount)
        lines=[]
        if accum>0: lines.append({"account":asset.accumulated_depreciation_account,"debit":accum,"credit":0,"asset":asset.name,"line_description":f"Clear accumulated depreciation {asset.name}"})
        if impairment>0:
            category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            self.impairment_account=self.impairment_account or asset.impairment_account or category.impairment_account
            _account(self.impairment_account,["Asset"])
            lines.append({"account":self.impairment_account,"debit":impairment,"credit":0,"asset":asset.name,"line_description":f"Clear accumulated impairment {asset.name}"})
        if proceeds>0: lines.append({"account":self.proceeds_account,"debit":proceeds,"credit":0,"asset":asset.name,"line_description":f"Gross disposal proceeds {asset.name}"})
        disposal_costs=D(self.disposal_costs)
        if disposal_costs>0:
            lines.append({"account":self.disposal_cost_account,"debit":disposal_costs,"credit":0,"asset":asset.name,"line_description":f"Disposal costs {asset.name}"})
            lines.append({"account":self.disposal_cost_payment_account,"debit":0,"credit":disposal_costs,"asset":asset.name,"line_description":f"Payment of disposal costs {asset.name}"})
        lines.append({"account":asset.asset_account,"debit":0,"credit":cost,"asset":asset.name,"line_description":f"Derecognise asset cost {asset.name}"})
        net_proceeds=proceeds-disposal_costs
        gross_gain_loss=proceeds-carrying
        if gross_gain_loss>0: lines.append({"account":self.gain_account,"debit":0,"credit":gross_gain_loss,"asset":asset.name,"line_description":f"Gain on disposal before disposal costs {asset.name}"})
        elif gross_gain_loss<0: lines.append({"account":self.loss_account,"debit":-gross_gain_loss,"credit":0,"asset":asset.name,"line_description":f"Loss on disposal before disposal costs {asset.name}"})
        _safe_post(self,self.disposal_date,_base_currency(),1,lines,"Asset Disposal",self.reason)
        from velora_erp.finance.doctype._utils import db_update, db_update_child
        for component in (asset.components or []):
            db_update_child("Fixed Asset Component",component.name,carrying_amount=0,status="Disposed")
        db_update(asset, status="Disposed", carrying_amount=0)
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(asset, "Disposal", self.disposal_date, self.doctype, self.name,
            from_values={"status": "Active", "carrying_amount": str(carrying)},
            to_values={"status": "Disposed", "carrying_amount": "0.00", "gain_loss": str(self.gain_loss)}, reason=self.reason)
