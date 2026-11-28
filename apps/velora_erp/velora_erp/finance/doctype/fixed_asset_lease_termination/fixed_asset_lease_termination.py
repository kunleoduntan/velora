from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from velora import Document, throw, get_doc, get_list, new_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved
from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.finance.validation import row
D=lambda v: Decimal(str(v if v not in (None, "") else 0))
M=lambda v: D(v).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)

def calculate_lease_termination(liability, rou_carrying, settlement, scope_percent):
    percent=D(scope_percent)
    if percent<=0 or percent>100: throw("Scope reduction must be greater than zero and not exceed 100%.")
    factor=percent/Decimal("100")
    liability_removed=M(D(liability)*factor)
    rou_removed=M(D(rou_carrying)*factor)
    settlement=M(settlement)
    return {"liability_derecognised":liability_removed,"rou_derecognised":rou_removed,"gain_loss":M(liability_removed-rou_removed-settlement)}


def account(name,root):
    a=row("Account",name,"name","root_type","disabled") if name else None
    if not a or a["disabled"] or a["root_type"]!=root: throw(f"Configure an active {root} account for lease termination.")
    return a

class FixedAssetLeaseTermination(Document):
    def validate(self):
        validate_approval_transition(self)
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True)
        if lease.docstatus!=1 or lease.status!="Active": throw("Select an active submitted lease.")
        if str(self.effective_date)<str(lease.lease_start_date) or str(self.effective_date)>str(lease.lease_end_date): throw("Effective Date must fall within the lease term.")
        if D(self.settlement_amount)<0: throw("Termination settlement cannot be negative.")
        if self.termination_type=="Partial Scope Reduction":
            overdue=get_list("Fixed Asset Lease Payment",filters={"parent":lease.name,"parenttype":"Fixed Asset Lease","parentfield":"payments"},fields=["payment_status","due_date"],limit=10000,ignore_permissions=True)
            if any(p.get("payment_status")!="Paid" and str(p.get("due_date") or "")<str(self.effective_date) for p in overdue):
                throw("Settle all overdue lease instalments before processing a partial scope reduction. Past-due cash flows cannot be proportionally reduced.")
        percent=D(self.scope_reduction_percent)
        if self.termination_type=="Full Termination": percent=Decimal("100")
        elif percent<=0 or percent>=100: throw("Partial Scope Reduction must be greater than zero and less than 100 percent.")
        if self.termination_type not in ("Full Termination","Partial Scope Reduction"): throw("Unsupported lease termination event.")
        rou=get_doc("Fixed Asset",lease.right_of_use_asset,ignore_permissions=True)
        if rou.status not in ("Leased","Active"): throw("The right-of-use asset is not active.")
        if rou.components: throw("Componentised right-of-use assets require component-level lease termination accounting and cannot be terminated through this aggregate workflow.")
        liability=D(lease.lease_liability_balance if lease.lease_liability_balance is not None else lease.present_value)
        carrying=D(rou.carrying_amount)
        self.scope_reduction_percent=percent
        result=calculate_lease_termination(liability,carrying,self.settlement_amount,percent)
        self.lease_liability_before=M(liability); self.lease_liability_derecognised=result["liability_derecognised"]
        self.rou_carrying_amount_before=M(carrying); self.rou_carrying_amount_derecognised=result["rou_derecognised"]
        gain=result["gain_loss"]
        self.gain_loss=gain
        if D(self.settlement_amount)>0: account(self.settlement_account,"Asset")
        if gain>0: account(self.gain_account,"Income")
        elif gain<0: account(self.loss_account,"Expense")
        account(lease.lease_liability_account,"Liability"); account(lease.rou_asset_account,"Asset")
        if D(rou.accumulated_depreciation)>0: account(rou.accumulated_depreciation_account,"Asset")
        if D(rou.impairment_loss)>0: account(rou.impairment_account,"Asset")
    def before_submit(self):
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True); lease._lock_and_check(); lease.reload()
        current=lease.lease_liability_balance if lease.lease_liability_balance is not None else lease.present_value
        if D(current)!=D(self.lease_liability_before): throw("Lease liability changed after this termination was prepared. Recalculate the termination.")
        ensure_approved(self,required=True)
    def on_submit(self):
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True); rou=get_doc("Fixed Asset",lease.right_of_use_asset,ignore_permissions=True)
        factor=D(self.scope_reduction_percent)/Decimal("100")
        cost=D(rou.acquisition_cost)+D(rou.revaluation_adjustment); accum=D(rou.accumulated_depreciation); impairment=D(rou.impairment_loss)
        remove_cost=M(cost*factor); remove_accum=M(accum*factor); remove_impairment=M(impairment*factor)
        liability=M(self.lease_liability_derecognised); carrying=M(remove_cost-remove_accum-remove_impairment)
        lines=[{"account":lease.lease_liability_account,"debit":liability,"credit":0,"asset":rou.name,"line_description":"Derecognise lease liability on scope reduction / termination"},
               {"account":lease.rou_asset_account,"debit":0,"credit":remove_cost,"asset":rou.name,"line_description":"Derecognise right-of-use asset cost"}]
        if remove_accum>0: lines.append({"account":rou.accumulated_depreciation_account,"debit":remove_accum,"credit":0,"asset":rou.name,"line_description":"Clear related accumulated depreciation"})
        if remove_impairment>0: lines.append({"account":rou.impairment_account,"debit":remove_impairment,"credit":0,"asset":rou.name,"line_description":"Clear related accumulated impairment"})
        if D(self.settlement_amount)>0: lines.append({"account":self.settlement_account,"debit":0,"credit":self.settlement_amount,"asset":rou.name,"line_description":"Lease termination settlement paid"})
        reserve_release=M(D(rou.revaluation_surplus)*factor)
        if reserve_release>0:
            category=get_doc("Fixed Asset Category",rou.asset_category,ignore_permissions=True)
            reserve_account=rou.revaluation_surplus_account or category.revaluation_surplus_account
            account(reserve_account,"Equity"); account(self.revaluation_surplus_transfer_account,"Equity")
            lines.append({"account":reserve_account,"debit":reserve_release,"credit":0,"asset":rou.name,"line_description":"Transfer ROU revaluation surplus on termination / scope reduction"})
            lines.append({"account":self.revaluation_surplus_transfer_account,"debit":0,"credit":reserve_release,"asset":rou.name,"line_description":"Transfer ROU revaluation surplus to retained earnings"})
        if D(self.gain_loss)>0: lines.append({"account":self.gain_account,"debit":0,"credit":self.gain_loss,"asset":rou.name,"line_description":"Gain on lease termination / scope reduction"})
        elif D(self.gain_loss)<0: lines.append({"account":self.loss_account,"debit":-D(self.gain_loss),"credit":0,"asset":rou.name,"line_description":"Loss on lease termination / scope reduction"})
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.effective_date,currency=lease.currency,exchange_rate=lease.exchange_rate or 1,lines=lines,posting_event="Original",remarks=self.reason,idempotency_key=f"lease-termination:{self.name}")
        db_update(self,posting_batch=batch.name)
        remaining=Decimal("1")-factor
        updates={"acquisition_cost":M(D(rou.acquisition_cost)*remaining),"revaluation_adjustment":M(D(rou.revaluation_adjustment)*remaining),"accumulated_depreciation":M(accum-remove_accum),"impairment_loss":M(impairment-remove_impairment),"carrying_amount":M(max(Decimal("0"),D(rou.carrying_amount)-D(self.rou_carrying_amount_derecognised))),"revaluation_surplus":M(D(rou.revaluation_surplus)*remaining),"impairment_against_revaluation_surplus":M(D(rou.impairment_against_revaluation_surplus)*remaining),"impairment_charged_to_expense":M(D(rou.impairment_charged_to_expense)*remaining)}
        if self.termination_type=="Full Termination": updates["status"]="Disposed"
        db_update(rou,**updates)
        db_update(lease,lease_liability_balance=M(D(self.lease_liability_before)-liability),status=("Terminated" if self.termination_type=="Full Termination" else "Active"))
        rows=get_list("Fixed Asset Lease Payment",filters={"parent":lease.name,"parenttype":"Fixed Asset Lease","parentfield":"payments"},fields=["name","payment_status","due_date","payment_amount","idx"],limit=10000,ignore_permissions=True)
        unpaid=[p for p in rows if p.get("payment_status")!="Paid"]
        future=sorted([p for p in unpaid if str(p.get("due_date") or "")>=str(self.effective_date)],key=lambda p:(str(p.get("due_date") or ""),int(p.get("idx") or 0)))
        supersede=unpaid if self.termination_type=="Full Termination" else future
        for p in supersede:
            db_update_child("Fixed Asset Lease Payment",p["name"],payment_status="Superseded")
        if self.termination_type=="Partial Scope Reduction":
            if not future:
                throw("A partial scope reduction requires an outstanding future lease payment schedule. Use full termination or correct the lease schedule first.")
            opening=M(D(self.lease_liability_before)-liability)
            annual=D(lease.discount_rate)/Decimal("100")
            previous=date.fromisoformat(str(self.effective_date)[:10])
            max_idx=max([int(p.get("idx") or 0) for p in rows] or [0])
            for idx,payment in enumerate(future,1):
                due=date.fromisoformat(str(payment["due_date"])[:10])
                days=max(0,(due-previous).days)
                interest=M(opening*((Decimal("1")+annual)**(D(days)/Decimal("365.25"))-Decimal("1")))
                amount=M(D(payment["payment_amount"])*(Decimal("1")-factor))
                principal=amount-interest
                if idx==len(future):
                    # Scale the remaining cash flows proportionally and true-up the final instalment for rounding.
                    amount=M(opening+interest)
                    principal=opening
                elif principal<=0:
                    throw(f"Scaled lease instalment {idx} does not cover its interest component after the scope reduction.")
                closing=M(opening-principal)
                child=new_doc("Fixed Asset Lease Payment",parent=lease.name,parenttype="Fixed Asset Lease",parentfield="payments",idx=max_idx+idx,
                    due_date=payment["due_date"],payment_amount=amount,payment_status="Scheduled",opening_liability=opening,
                    interest_expense=interest,principal_reduction=principal,closing_liability=closing)
                child.insert(ignore_permissions=True)
                opening=closing; previous=due
            if abs(opening)>Decimal("0.01"):
                throw("The revised lease payment schedule does not fully amortise the remaining liability.")
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(rou,"Lease Termination" if self.termination_type=="Full Termination" else "Lease Scope Reduction",self.effective_date,self.doctype,self.name,from_values={"carrying_amount":str(self.rou_carrying_amount_before)},to_values={"carrying_amount":str(updates["carrying_amount"]),"status":updates.get("status",rou.status)},reason=self.reason)
