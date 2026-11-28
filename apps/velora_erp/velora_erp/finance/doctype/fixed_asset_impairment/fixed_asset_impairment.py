from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.validation import row
CENT=Decimal("0.01")
D=lambda v: Decimal(str(v or 0))
def money(v): return D(v).quantize(CENT,rounding=ROUND_HALF_UP)
def calculate_impairment_movement(action, carrying, recoverable, impairment_loss, no_impairment_carrying):
    carrying,recoverable=D(carrying),D(recoverable); impairment_loss,no_impairment_carrying=D(impairment_loss),D(no_impairment_carrying)
    if action=="Recognise Impairment":
        movement=carrying-recoverable
        if movement<=0: throw("Recoverable Amount must be lower than Carrying Amount to recognise an impairment loss.")
        return money(movement)
    if action=="Reverse Impairment":
        if impairment_loss<=0: throw("There is no recognised impairment loss available for reversal.")
        movement=min(recoverable-carrying,impairment_loss,max(Decimal("0"),no_impairment_carrying-carrying))
        if movement<=0: throw("Recoverable Amount does not support an impairment reversal, or the reversal ceiling has been reached.")
        return money(movement)
    throw("Select a valid impairment assessment action.")
def tracked_impairment(asset):
    reserve=D(asset.impairment_against_revaluation_surplus); pnl=D(asset.impairment_charged_to_expense); total=D(asset.impairment_loss)
    if reserve+pnl<total: pnl+=total-reserve-pnl  # legacy impairment is assumed to have been charged to P&L
    if reserve+pnl>total: throw("Asset impairment allocation tracking exceeds the recognised impairment balance. Reconcile before reversal.")
    return reserve,pnl
def _account(name,root):
    a=row("Account",name,"name","disabled","root_type") if name else None
    if not a or a["disabled"] or a["root_type"]!=root: throw(f"Configure an active {root} account for the impairment movement.")
    return a
class FixedAssetImpairment(Document):
    def validate(self):
        validate_approval_transition(self)
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True)
        if asset.status not in ("Active","Leased"): throw("Only active owned or right-of-use assets can be assessed for impairment.")
        if asset.components: throw("This asset uses component accounting. Component-level recoverable amounts are required; aggregate asset-level impairment is blocked to protect component carrying values.")
        if str(self.assessment_date)<str(asset.acquisition_date): throw("Assessment Date cannot be before Acquisition Date.")
        carrying=D(asset.carrying_amount); recoverable=D(self.recoverable_amount)
        if recoverable<0: throw("Recoverable Amount cannot be negative.")
        self.carrying_amount_before=carrying
        category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
        self.impairment_account=self.impairment_account or asset.impairment_account or category.impairment_account
        self.impairment_expense_account=self.impairment_expense_account or asset.impairment_expense_account or category.impairment_expense_account
        self.impairment_reversal_account=self.impairment_reversal_account or asset.impairment_reversal_account or category.impairment_reversal_account
        self.revaluation_surplus_account=self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account
        ceiling=max(D(asset.residual_value),D(asset.impairment_ceiling_carrying_amount) or (carrying+D(asset.impairment_loss)))
        self.impairment_movement=calculate_impairment_movement(self.action,carrying,recoverable,asset.impairment_loss,ceiling)
        reserve_tracked,pnl_tracked=tracked_impairment(asset)
        if self.action=="Recognise Impairment":
            reserve_movement=min(D(self.impairment_movement),D(asset.revaluation_surplus))
            pnl_movement=D(self.impairment_movement)-reserve_movement
            if reserve_movement>0: _account(self.revaluation_surplus_account,"Equity")
            if pnl_movement>0: _account(self.impairment_expense_account,"Expense")
            _account(self.impairment_account,"Asset")
        else:
            pnl_movement=min(D(self.impairment_movement),pnl_tracked)
            reserve_movement=D(self.impairment_movement)-pnl_movement
            if reserve_movement>reserve_tracked: throw("Impairment reversal allocation exceeds the amount previously charged against revaluation surplus.")
            if pnl_movement>0: _account(self.impairment_reversal_account,"Income")
            if reserve_movement>0: _account(self.revaluation_surplus_account,"Equity")
            _account(self.impairment_account,"Asset")
        self.revaluation_surplus_movement=reserve_movement
        self.profit_or_loss_movement=pnl_movement
        if not self.impairment_indicators and not self.valuation_reference: throw("Record impairment indicators or a valuation reference as supporting evidence.")
    def before_submit(self): ensure_approved(self,required=True)
    def on_submit(self):
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True); amount=D(self.impairment_movement)
        reserve_movement=D(self.revaluation_surplus_movement); pnl_movement=D(self.profit_or_loss_movement)
        reserve_tracked,pnl_tracked=tracked_impairment(asset); old_impairment=D(asset.impairment_loss)
        lines=[]
        if self.action=="Recognise Impairment":
            if reserve_movement>0: lines.append({"account":self.revaluation_surplus_account,"debit":reserve_movement,"credit":0,"asset":asset.name,"line_description":f"Impairment charged against revaluation surplus {asset.name}"})
            if pnl_movement>0: lines.append({"account":self.impairment_expense_account,"debit":pnl_movement,"credit":0,"asset":asset.name,"line_description":f"Impairment loss {asset.name}"})
            lines.append({"account":self.impairment_account,"debit":0,"credit":amount,"asset":asset.name,"line_description":f"Accumulated impairment {asset.name}"})
            new_impairment=old_impairment+amount; new_reserve_track=reserve_tracked+reserve_movement; new_pnl_track=pnl_tracked+pnl_movement
            new_revaluation_surplus=D(asset.revaluation_surplus)-reserve_movement
        else:
            lines.append({"account":self.impairment_account,"debit":amount,"credit":0,"asset":asset.name,"line_description":f"Reverse accumulated impairment {asset.name}"})
            if pnl_movement>0: lines.append({"account":self.impairment_reversal_account,"debit":0,"credit":pnl_movement,"asset":asset.name,"line_description":f"Impairment reversal income {asset.name}"})
            if reserve_movement>0: lines.append({"account":self.revaluation_surplus_account,"debit":0,"credit":reserve_movement,"asset":asset.name,"line_description":f"Restore revaluation surplus after impairment reversal {asset.name}"})
            new_impairment=old_impairment-amount; new_reserve_track=reserve_tracked-reserve_movement; new_pnl_track=pnl_tracked-pnl_movement
            new_revaluation_surplus=D(asset.revaluation_surplus)+reserve_movement
        settings=finance_settings()
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.assessment_date,currency=settings["base_currency"],exchange_rate=1,lines=lines,posting_event="Original",remarks=self.remarks or f"{self.action} for {asset.name}",idempotency_key=f"fixed-asset-impairment:{self.name}")
        db_update(self,posting_batch=batch.name)
        ceiling=D(asset.impairment_ceiling_carrying_amount)
        if self.action=="Recognise Impairment" and ceiling<=0: ceiling=D(asset.carrying_amount)+D(asset.impairment_loss)
        if self.action=="Reverse Impairment" and new_impairment<=0: ceiling=Decimal("0")
        new_carrying=money(D(asset.carrying_amount)+(amount if self.action=="Reverse Impairment" else -amount))
        db_update(asset,impairment_loss=money(new_impairment),carrying_amount=new_carrying,impairment_ceiling_carrying_amount=money(ceiling),revaluation_surplus=money(new_revaluation_surplus),impairment_against_revaluation_surplus=money(new_reserve_track),impairment_charged_to_expense=money(new_pnl_track))
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(asset,"Impairment",self.assessment_date,self.doctype,self.name,from_values={"carrying_amount":str(self.carrying_amount_before),"impairment_loss":str(old_impairment)},to_values={"carrying_amount":str(new_carrying),"impairment_loss":str(new_impairment)},reason=self.remarks or self.action)
