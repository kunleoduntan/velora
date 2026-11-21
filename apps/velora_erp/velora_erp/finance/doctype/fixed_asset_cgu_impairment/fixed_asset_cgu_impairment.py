from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.doctype._utils import db_update
from velora_erp.finance.validation import row
D=lambda x: Decimal(str(x or 0))
M=lambda x: D(x).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
def allocate_cgu_impairment(carrying_values, recoverable_amount, floors=None):
    """Allocate a CGU loss pro-rata, to exact cents, subject to individual floors."""
    floors=floors or {}; carrying={k:D(v) for k,v in carrying_values.items()}; recoverable=D(recoverable_amount)
    if not carrying or any(v<0 for v in carrying.values()): throw("CGU assets must have non-negative carrying amounts.")
    if any(D(floors.get(k,0))<0 or D(floors.get(k,0))>v for k,v in carrying.items()): throw("Individual recoverable floors must be between zero and the asset carrying amount.")
    total=sum(carrying.values(),Decimal("0")); loss=M(total-recoverable)
    if loss<=0: throw("CGU recoverable amount is not below the CGU carrying amount; no impairment loss is due.")
    target=int(loss*100)
    capacity={k:int(M(v-D(floors.get(k,0)))*100) for k,v in carrying.items()}
    if target>sum(capacity.values()): throw("CGU impairment exceeds the amount allocable to fixed assets after individual recoverable amount floors. Assess goodwill and other CGU assets first.")
    allocated={k:0 for k in carrying}; remaining=target
    while remaining>0:
        active=[k for k in carrying if capacity[k]>allocated[k]]
        if not active: throw("Unable to allocate the full CGU impairment loss within individual asset floors.")
        weight_total=sum((carrying[k] for k in active),Decimal("0"))
        if weight_total<=0: weight_total=Decimal(len(active))
        exact={k:Decimal(remaining)*(carrying[k] if weight_total!=Decimal(len(active)) or any(carrying[x] for x in active) else Decimal("1"))/weight_total for k in active}
        base_add={k:min(capacity[k]-allocated[k],int(exact[k])) for k in active}
        used=sum(base_add.values())
        for k,v in base_add.items(): allocated[k]+=v
        remaining-=used
        if remaining<=0: break
        fractions=sorted(active,key=lambda k:(exact[k]-int(exact[k]),carrying[k],str(k)),reverse=True)
        distributed=0
        for k in fractions:
            if remaining<=0: break
            if allocated[k]<capacity[k]: allocated[k]+=1; remaining-=1; distributed+=1
        if used==0 and distributed==0: throw("Unable to allocate the full CGU impairment loss within individual asset floors.")
    return {k:(Decimal(v)/Decimal("100")).quantize(Decimal("0.01")) for k,v in allocated.items()}

class FixedAssetCGUImpairment(Document):
    def validate(self):
        validate_approval_transition(self)
        cgu=get_doc("Fixed Asset CGU",self.cgu,ignore_permissions=True)
        if cgu.disabled: throw("Select an active CGU.")
        if not self.valuation_reference: throw("A valuation reference is required.")
        if D(self.recoverable_amount)<0: throw("CGU Recoverable Amount cannot be negative.")
        carrying={}; floors={}; assets={}; other_by_ref={}; goodwill=[]; other_non_goodwill={}
        for member in (cgu.assets or []):
            asset=get_doc("Fixed Asset",member.asset,ignore_permissions=True)
            if asset.status not in ("Active","Leased"): throw(f"CGU member {member.asset} is not an active asset.")
            if asset.components: throw(f"CGU asset {asset.name} uses component accounting; use component-level impairment assessments before including it in a CGU allocation.")
            if asset.name in carrying: throw(f"Asset {asset.name} appears more than once in the CGU.")
            key="FA:"+asset.name; carrying[key]=D(asset.carrying_amount); floors[key]=D(member.individual_recoverable_floor); assets[key]=asset
        for item in (cgu.other_assets or []):
            ref=(item.reference_code or "").strip()
            if not ref or ref in other_by_ref: throw("Goodwill and other CGU asset references must be populated and unique.")
            value=D(item.carrying_amount); floor=D(item.individual_recoverable_floor)
            if value<0 or floor<0 or floor>value: throw(f"CGU other asset {ref}: carrying amount and recoverable floor are invalid.")
            other_by_ref[ref]=item
            if item.asset_type=="Goodwill": goodwill.append((ref,item))
            else: other_non_goodwill["OA:"+ref]=item
        total=sum(carrying.values(),Decimal("0"))+sum((D(x.carrying_amount) for x in other_by_ref.values()),Decimal("0"))
        total_loss=M(total-D(self.recoverable_amount))
        if total_loss<=0: throw("CGU recoverable amount is not below the total CGU carrying amount; no impairment is due.")
        remaining=total_loss; other_allocations={}
        self.lines=[]; self.other_asset_lines=[]
        # IAS 36: allocate impairment to goodwill first; goodwill impairment is not reversed.
        for ref,item in sorted(goodwill,key=lambda x:x[0]):
            if D(item.individual_recoverable_floor)!=0:
                throw(f"Goodwill {ref} must have a zero individual recoverable floor; impairment is allocated to goodwill first.")
            capacity=D(item.carrying_amount)
            amount=min(remaining,capacity)
            if amount>0:
                other_allocations[ref]=amount; remaining=M(remaining-amount)
            if remaining<=0: break
        pool_values={k:v for k,v in carrying.items()}
        pool_floors={k:v for k,v in floors.items()}
        for key,item in other_non_goodwill.items():
            pool_values[key]=D(item.carrying_amount); pool_floors[key]=D(item.individual_recoverable_floor)
        pool_total=sum(pool_values.values(),Decimal("0"))
        if remaining>0:
            if not pool_values: throw("CGU impairment remains after goodwill allocation but no other eligible assets are configured.")
            pool_recoverable=pool_total-remaining
            pool_allocations=allocate_cgu_impairment(pool_values,pool_recoverable,pool_floors)
            for key,amount in pool_allocations.items():
                if amount<=0: continue
                if key.startswith("FA:"):
                    asset=assets[key]; category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                    impairment_account=asset.impairment_account or category.impairment_account
                    expense_account=asset.impairment_expense_account or category.impairment_expense_account
                    reserve_account=asset.revaluation_surplus_account or category.revaluation_surplus_account or self.revaluation_surplus_account
                    reserve_release=min(amount,D(asset.revaluation_surplus)); expense_amount=M(amount-reserve_release)
                    impairment=row("Account",impairment_account,"name","disabled","root_type") if impairment_account else None
                    if not impairment or impairment["disabled"] or impairment["root_type"]!="Asset": throw(f"Configure an active Asset accumulated impairment account for asset {asset.name}.")
                    if reserve_release>0:
                        reserve=row("Account",reserve_account,"name","disabled","root_type") if reserve_account else None
                        if not reserve or reserve["disabled"] or reserve["root_type"]!="Equity": throw(f"Configure an active Equity revaluation surplus account for asset {asset.name}.")
                    if expense_amount>0:
                        expense=row("Account",expense_account,"name","disabled","root_type") if expense_account else None
                        if not expense or expense["disabled"] or expense["root_type"]!="Expense": throw(f"Configure an active Expense impairment account for asset {asset.name}.")
                    self.append("lines",{"asset":asset.name,"carrying_amount":carrying[key],"recoverable_floor":floors[key],"allocated_impairment":amount,"post_impairment_amount":M(carrying[key]-amount),"revaluation_surplus_release":reserve_release,"impairment_expense_amount":expense_amount})
                else:
                    ref=key[3:]; item=other_by_ref[ref]
                    reserve_release=Decimal("0") if item.asset_type=="Goodwill" else min(amount,D(item.revaluation_surplus))
                    expense_amount=M(amount-reserve_release)
                    imp=row("Account",item.impairment_account,"name","disabled","root_type")
                    exp=row("Account",item.impairment_expense_account,"name","disabled","root_type")
                    if not imp or imp["disabled"] or imp["root_type"]!="Asset": throw(f"CGU other asset {ref}: accumulated impairment account must be an active Asset account.")
                    if not exp or exp["disabled"] or exp["root_type"]!="Expense": throw(f"CGU other asset {ref}: impairment expense account must be an active Expense account.")
                    if reserve_release>0:
                        reserve=row("Account",item.revaluation_surplus_account,"name","disabled","root_type") if item.revaluation_surplus_account else None
                        if not reserve or reserve["disabled"] or reserve["root_type"]!="Equity": throw(f"CGU other asset {ref}: revaluation surplus account must be an active Equity account.")
                    other_allocations[ref]=amount
        self.carrying_amount_before=M(total)
        self.impairment_loss=M(total_loss)
        for ref,item in other_by_ref.items():
            amount=M(other_allocations.get(ref,0))
            if amount<=0: continue
            reserve_release=Decimal("0") if item.asset_type=="Goodwill" else min(amount,D(item.revaluation_surplus))
            expense_amount=M(amount-reserve_release)
            imp=row("Account",item.impairment_account,"name","disabled","root_type")
            exp=row("Account",item.impairment_expense_account,"name","disabled","root_type")
            if not imp or imp["disabled"] or imp["root_type"]!="Asset": throw(f"CGU other asset {ref}: accumulated impairment account must be an active Asset account.")
            if not exp or exp["disabled"] or exp["root_type"]!="Expense": throw(f"CGU other asset {ref}: impairment expense account must be an active Expense account.")
            self.append("other_asset_lines",{"reference_code":ref,"asset_type":item.asset_type,"carrying_amount_before":item.carrying_amount,"recoverable_floor":item.individual_recoverable_floor,"allocated_impairment":amount,"post_impairment_amount":M(D(item.carrying_amount)-amount),"revaluation_surplus_release":reserve_release,"impairment_expense_amount":expense_amount})
        if not self.lines and not self.other_asset_lines: throw("No impairment allocation could be made within the configured asset floors.")
        self._link_children()

    def before_submit(self): ensure_approved(self,required=True)

    def on_submit(self):
        lines=[]; updates=[]
        from velora_erp.finance.doctype.fixed_asset_impairment.fixed_asset_impairment import tracked_impairment
        for line in self.lines:
            asset=get_doc("Fixed Asset",line.asset,ignore_permissions=True); category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            impairment_account=asset.impairment_account or category.impairment_account
            expense_account=asset.impairment_expense_account or category.impairment_expense_account
            reserve_account=asset.revaluation_surplus_account or category.revaluation_surplus_account or self.revaluation_surplus_account
            amount=D(line.allocated_impairment); reserve_release=D(line.revaluation_surplus_release); expense_amount=D(line.impairment_expense_amount)
            dimensions={"cost_centre":asset.cost_centre or None,"business_unit":asset.business_unit or None,"asset":asset.name}
            if reserve_release>0: lines.append({"account":reserve_account,"debit":reserve_release,"credit":0,"line_description":f"CGU impairment against revaluation surplus {asset.name}",**dimensions})
            if expense_amount>0: lines.append({"account":expense_account,"debit":expense_amount,"credit":0,"line_description":f"CGU impairment expense {asset.name}",**dimensions})
            lines.append({"account":impairment_account,"debit":0,"credit":amount,"line_description":f"Accumulated CGU impairment {asset.name}",**dimensions})
            reserve_tracked,pnl_tracked=tracked_impairment(asset)
            ceiling=D(asset.impairment_ceiling_carrying_amount) or D(asset.carrying_amount)+D(asset.impairment_loss)
            updates.append((asset,M(D(asset.carrying_amount)-amount),M(D(asset.impairment_loss)+amount),M(ceiling),M(D(asset.revaluation_surplus)-reserve_release),M(reserve_tracked+reserve_release),M(pnl_tracked+expense_amount)))
        cgu=get_doc("Fixed Asset CGU",self.cgu,ignore_permissions=True)
        for line in self.other_asset_lines:
            item=next((x for x in (cgu.other_assets or []) if x.reference_code==line.reference_code),None)
            if not item: throw(f"CGU other asset {line.reference_code} disappeared before posting.")
            amount=D(line.allocated_impairment); reserve_release=D(line.revaluation_surplus_release); expense_amount=D(line.impairment_expense_amount)
            if reserve_release>0: lines.append({"account":item.revaluation_surplus_account,"debit":reserve_release,"credit":0,"line_description":f"CGU impairment against revaluation surplus {item.reference_code}"})
            if expense_amount>0: lines.append({"account":item.impairment_expense_account,"debit":expense_amount,"credit":0,"line_description":f"CGU impairment expense {item.reference_code}"})
            lines.append({"account":item.impairment_account,"debit":0,"credit":amount,"line_description":f"Accumulated CGU impairment {item.reference_code}"})
            db_update_child("Fixed Asset CGU Other Asset",item.name,carrying_amount=M(D(item.carrying_amount)-amount),accumulated_impairment=M(D(item.accumulated_impairment)+amount),revaluation_surplus=M(D(item.revaluation_surplus)-reserve_release),impairment_against_revaluation_surplus=M(D(item.impairment_against_revaluation_surplus)+reserve_release),impairment_charged_to_expense=M(D(item.impairment_charged_to_expense)+expense_amount),impairment_ceiling_carrying_amount=(item.impairment_ceiling_carrying_amount or item.carrying_amount))
        settings=finance_settings()
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.assessment_date,currency=settings["base_currency"],exchange_rate=1,lines=lines,posting_event="Original",remarks=f"CGU impairment {self.cgu}: {self.valuation_reference}",idempotency_key=f"cgu-impairment:{self.name}")
        db_update(self,posting_batch=batch.name)
        for asset,carrying,loss,ceiling,surplus,reserve_track,pnl_track in updates:
            db_update(asset,carrying_amount=carrying,impairment_loss=loss,impairment_ceiling_carrying_amount=ceiling,revaluation_surplus=surplus,impairment_against_revaluation_surplus=reserve_track,impairment_charged_to_expense=pnl_track)
            from velora_erp.finance.asset_history import record_asset_history
            record_asset_history(asset,"Impairment",self.assessment_date,self.doctype,self.name,from_values={},to_values={"carrying_amount":str(carrying),"impairment_loss":str(loss)},reason=f"CGU {self.cgu}; valuation {self.valuation_reference}")

