from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.finance.validation import row
D=lambda v: Decimal(str(v if v not in (None, "") else 0))
M=lambda v: D(v).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)

def maximum_impairment_reversal(current_carrying_amount, accumulated_impairment, no_impairment_ceiling):
    return M(min(D(accumulated_impairment), max(Decimal("0"), D(no_impairment_ceiling)-D(current_carrying_amount))))

class FixedAssetCGUImpairmentReversal(Document):
    def validate(self):
        validate_approval_transition(self)
        cgu=get_doc("Fixed Asset CGU",self.cgu,ignore_permissions=True)
        if cgu.disabled: throw("Select an active CGU.")
        if not self.valuation_reference or not (self.lines or self.other_asset_lines): throw("Valuation Reference and at least one reversal line are required.")
        members={m.asset for m in (cgu.assets or [])}; seen=set()
        for i,line in enumerate(self.lines,1):
            if line.asset not in members: throw(f"Line {i}: asset is not a member of the selected CGU.")
            if line.asset in seen: throw(f"Line {i}: duplicate asset reversal.")
            seen.add(line.asset)
            asset=get_doc("Fixed Asset",line.asset,ignore_permissions=True)
            if asset.status not in ("Active","Leased"): throw(f"Line {i}: asset is not active.")
            if asset.components: throw(f"Line {i}: componentised asset reversal must be processed at component level.")
            ceiling=D(asset.impairment_ceiling_carrying_amount)
            maximum=maximum_impairment_reversal(asset.carrying_amount,asset.impairment_loss,ceiling)
            amount=M(line.amount)
            if amount<=0 or amount>maximum: throw(f"Line {i}: reversal exceeds the remaining impairment or IAS 36 carrying amount ceiling ({M(maximum)}).")
            from velora_erp.finance.doctype.fixed_asset_impairment.fixed_asset_impairment import tracked_impairment
            reserve_tracked,pnl_tracked=tracked_impairment(asset)
            pnl=min(amount,pnl_tracked); reserve=M(amount-pnl)
            line.carrying_amount_before=M(asset.carrying_amount); line.maximum_reversal=M(maximum)
            line.reversal_to_profit_or_loss=M(pnl); line.reversal_to_revaluation_surplus=reserve
            category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            contra=asset.impairment_account or category.impairment_account
            acc=row("Account",contra,"name","disabled","root_type") if contra else None
            if not acc or acc["disabled"] or acc["root_type"]!="Asset": throw(f"Line {i}: configure an active accumulated impairment account.")
            if pnl>0:
                income=asset.impairment_reversal_account or category.impairment_reversal_account
                a=row("Account",income,"name","disabled","root_type") if income else None
                if not a or a["disabled"] or a["root_type"]!="Income": throw(f"Line {i}: configure an active impairment reversal income account.")
            if reserve>0:
                equity=asset.revaluation_surplus_account or category.revaluation_surplus_account
                a=row("Account",equity,"name","disabled","root_type") if equity else None
                if not a or a["disabled"] or a["root_type"]!="Equity": throw(f"Line {i}: configure an active revaluation surplus account.")
        other_seen=set()
        for i,line in enumerate(self.other_asset_lines or [],1):
            item=next((x for x in (cgu.other_assets or []) if x.reference_code==line.reference_code),None)
            if not item: throw(f"Other asset reversal line {i}: asset is not part of the selected CGU.")
            if line.reference_code in other_seen: throw(f"Other asset reversal line {i}: duplicate asset reference.")
            other_seen.add(line.reference_code)
            if item.asset_type=="Goodwill": throw(f"Goodwill {item.reference_code} impairment cannot be reversed under IAS 36.")
            ceiling=D(item.impairment_ceiling_carrying_amount)
            maximum=maximum_impairment_reversal(item.carrying_amount,item.accumulated_impairment,ceiling)
            amount=M(line.amount)
            if amount<=0 or amount>maximum: throw(f"Other asset {item.reference_code}: reversal exceeds the remaining impairment or no-impairment carrying amount ceiling ({maximum}).")
            reserve_tracked=D(item.impairment_against_revaluation_surplus); pnl_tracked=D(item.impairment_charged_to_expense)
            total=D(item.accumulated_impairment)
            if reserve_tracked+pnl_tracked<total: pnl_tracked+=total-reserve_tracked-pnl_tracked
            if reserve_tracked+pnl_tracked>total: throw(f"Other asset {item.reference_code}: impairment allocation tracking exceeds accumulated impairment.")
            pnl=min(amount,pnl_tracked); reserve=M(amount-pnl)
            line.carrying_amount_before=M(item.carrying_amount); line.maximum_reversal=M(maximum)
            line.reversal_to_profit_or_loss=M(pnl); line.reversal_to_revaluation_surplus=reserve
            imp=row("Account",item.impairment_account,"name","disabled","root_type")
            if not imp or imp["disabled"] or imp["root_type"]!="Asset": throw(f"Other asset {item.reference_code}: accumulated impairment account must be an active Asset account.")
            if pnl>0:
                income=row("Account",item.impairment_reversal_account,"name","disabled","root_type")
                if not income or income["disabled"] or income["root_type"]!="Income": throw(f"Other asset {item.reference_code}: impairment reversal account must be an active Income account.")
            if reserve>0:
                equity=row("Account",item.revaluation_surplus_account,"name","disabled","root_type") if item.revaluation_surplus_account else None
                if not equity or equity["disabled"] or equity["root_type"]!="Equity": throw(f"Other asset {item.reference_code}: revaluation surplus account must be an active Equity account.")
        self._link_children()
    def before_submit(self): ensure_approved(self,required=True)
    def on_submit(self):
        lines=[]; updates=[]
        for line in self.lines:
            asset=get_doc("Fixed Asset",line.asset,ignore_permissions=True); category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            amount=M(line.amount); pnl=M(line.reversal_to_profit_or_loss); reserve=M(line.reversal_to_revaluation_surplus)
            contra=asset.impairment_account or category.impairment_account
            dimensions={"asset":asset.name,"cost_centre":asset.cost_centre or None,"business_unit":asset.business_unit or None}
            lines.append({"account":contra,"debit":amount,"credit":0,"line_description":"Reverse CGU accumulated impairment",**dimensions})
            if pnl>0: lines.append({"account":asset.impairment_reversal_account or category.impairment_reversal_account,"debit":0,"credit":pnl,"line_description":"CGU impairment reversal through profit or loss",**dimensions})
            if reserve>0: lines.append({"account":asset.revaluation_surplus_account or category.revaluation_surplus_account,"debit":0,"credit":reserve,"line_description":"Restore revaluation surplus on CGU impairment reversal",**dimensions})
            from velora_erp.finance.doctype.fixed_asset_impairment.fixed_asset_impairment import tracked_impairment
            reserve_tracked,pnl_tracked=tracked_impairment(asset)
            updates.append((asset,M(D(asset.carrying_amount)+amount),M(D(asset.impairment_loss)-amount),M(pnl_tracked-pnl),M(reserve_tracked-reserve),M(D(asset.revaluation_surplus)+reserve)))
        cgu=get_doc("Fixed Asset CGU",self.cgu,ignore_permissions=True)
        for line in (self.other_asset_lines or []):
            item=next((x for x in (cgu.other_assets or []) if x.reference_code==line.reference_code),None)
            if not item: throw(f"CGU other asset {line.reference_code} disappeared before reversal posting.")
            amount=M(line.amount); pnl=M(line.reversal_to_profit_or_loss); reserve=M(line.reversal_to_revaluation_surplus)
            lines.append({"account":item.impairment_account,"debit":amount,"credit":0,"line_description":f"Reverse accumulated CGU impairment {item.reference_code}"})
            if pnl>0: lines.append({"account":item.impairment_reversal_account,"debit":0,"credit":pnl,"line_description":f"CGU impairment reversal through P&L {item.reference_code}"})
            if reserve>0: lines.append({"account":item.revaluation_surplus_account,"debit":0,"credit":reserve,"line_description":f"Restore CGU revaluation surplus {item.reference_code}"})
            reserve_track=D(item.impairment_against_revaluation_surplus); pnl_track=D(item.impairment_charged_to_expense); total=D(item.accumulated_impairment)
            if reserve_track+pnl_track<total: pnl_track+=total-reserve_track-pnl_track
            db_update_child("Fixed Asset CGU Other Asset",item.name,carrying_amount=M(D(item.carrying_amount)+amount),accumulated_impairment=M(total-amount),impairment_charged_to_expense=M(pnl_track-pnl),impairment_against_revaluation_surplus=M(reserve_track-reserve),revaluation_surplus=M(D(item.revaluation_surplus)+reserve))
        settings=finance_settings(); batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.reversal_date,currency=settings["base_currency"],exchange_rate=1,lines=lines,posting_event="Original",remarks=f"CGU impairment reversal {self.cgu}: {self.valuation_reference}",idempotency_key=f"cgu-impairment-reversal:{self.name}")
        db_update(self,posting_batch=batch.name)
        for asset,carrying,impairment,pnl,reserve_track,surplus in updates:
            db_update(asset,carrying_amount=carrying,impairment_loss=impairment,impairment_charged_to_expense=pnl,impairment_against_revaluation_surplus=reserve_track,revaluation_surplus=surplus)
            from velora_erp.finance.asset_history import record_asset_history
            record_asset_history(asset,"Impairment Reversal",self.reversal_date,self.doctype,self.name,from_values={},to_values={"carrying_amount":str(carrying),"impairment_loss":str(impairment)},reason=self.reason)
