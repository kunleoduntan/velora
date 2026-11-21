from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from velora import Document, throw, get_doc, get_list, new_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved
from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.finance.validation import row
D=lambda x: Decimal(str(x or 0))
M=lambda x: D(x).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
def present_value_remaining(payments, annual_rate, effective_date):
    rate=D(annual_rate)/Decimal("100")
    if not rate.is_finite() or rate<0: throw("Revised discount rate must be finite and cannot be negative.")
    base=date.fromisoformat(str(effective_date)[:10]); total=Decimal("0")
    previous=None
    for p in payments:
        due=date.fromisoformat(str(p.due_date)[:10])
        if previous and due<=previous: throw("Revised lease payment dates must be strictly increasing.")
        previous=due
        if D(p.payment_amount)<=0: throw("Revised lease payments must be greater than zero.")
        days=max(0,(due-base).days)
        total+=D(p.payment_amount)/((Decimal("1")+rate)**(D(days)/Decimal("365.25")))
    return M(total)
class FixedAssetLeaseModification(Document):
    def validate(self):
        validate_approval_transition(self)
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True)
        if lease.docstatus!=1 or lease.status!="Active": throw("Select an active submitted lease.")
        if str(self.effective_date)<str(lease.lease_start_date): throw("Modification Effective Date cannot precede lease commencement.")
        if str(self.effective_date)>str(lease.lease_end_date): throw("Modification Effective Date cannot be after lease expiry.")
        paid_dates=[str(p.due_date) for p in (lease.payments or []) if p.payment_status=="Paid"]
        if paid_dates and str(self.effective_date)<max(paid_dates): throw("Modification Effective Date cannot precede an already settled lease instalment.")
        if not self.reason_details or not self.payments: throw("Reason Details and revised remaining payments are required.")
        if any(str(p.due_date) < str(self.effective_date) for p in self.payments): throw("Revised payment dates must be on or after the modification effective date.")
        if self.modification_reason not in ("Change in Lease Consideration","Change in Lease Term","Change in Discount Rate","Other Non-scope Modification"):
            throw("Scope reductions and lease terminations are not supported in this release; do not use this form for those events.")
        if self.modification_reason=="Change in Lease Term":
            if not self.revised_lease_end_date or str(self.revised_lease_end_date)<=str(self.effective_date):
                throw("A revised lease end date after the modification effective date is required for a lease-term change.")
            if str(self.revised_lease_end_date)<=str(lease.lease_end_date):
                throw("This release supports lease-term extensions only. Shortening and scope reduction are not supported in this release.")
        effective_end=self.revised_lease_end_date if self.modification_reason=="Change in Lease Term" else lease.lease_end_date
        if any(str(p.due_date)>str(effective_end) for p in self.payments): throw("A revised payment date cannot be after the revised lease end date.")
        old_liability=D(lease.lease_liability_balance if lease.lease_liability_balance is not None else lease.present_value)
        new_liability=present_value_remaining(self.payments,self.discount_rate,self.effective_date)
        delta=M(new_liability-old_liability)
        rou=get_doc("Fixed Asset",lease.right_of_use_asset,ignore_permissions=True)
        rou_adjustment=delta; gain=Decimal("0.00")
        if delta<0:
            reduction=-delta; depreciable_headroom=max(Decimal("0"),D(rou.carrying_amount)-D(rou.residual_value)); rou_adjustment=-min(reduction,depreciable_headroom); gain=M(reduction+rou_adjustment)
        self.liability_before=old_liability; self.remeasured_liability=new_liability
        self.liability_adjustment=delta; self.rou_adjustment=rou_adjustment; self.gain_on_remeasurement=gain
        if not self.payments: throw("At least one revised payment is required.")
        liability_account=row("Account",lease.lease_liability_account,"name","disabled","root_type")
        if not liability_account or liability_account["disabled"] or liability_account["root_type"]!="Liability": throw("Lease Liability Account must be an active Liability account.")
        if gain>0:
            gain_account=row("Account",lease.remeasurement_gain_account,"name","disabled","root_type") if lease.remeasurement_gain_account else None
            if not gain_account or gain_account["disabled"] or gain_account["root_type"]!="Income": throw("Configure an active Lease Remeasurement Gain Account before posting a liability reduction that exceeds the ROU carrying amount.")
    def before_submit(self):
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True)
        lease._lock_and_check(); lease.reload()
        current_liability=lease.lease_liability_balance if lease.lease_liability_balance is not None else lease.present_value
        if D(current_liability)!=D(self.liability_before): throw("The lease liability changed after this modification was calculated. Reopen and recalculate the modification.")
        ensure_approved(self,required=True)
    def on_submit(self):
        lease=get_doc("Fixed Asset Lease",self.lease,ignore_permissions=True); rou=get_doc("Fixed Asset",lease.right_of_use_asset,ignore_permissions=True)
        delta=D(self.liability_adjustment); rou_adj=D(self.rou_adjustment); gain=D(self.gain_on_remeasurement)
        lines=[]
        if delta>0:
            lines=[{"account":lease.rou_asset_account,"debit":delta,"credit":0,"asset":rou.name,"line_description":"Lease liability remeasurement increase"},{"account":lease.lease_liability_account,"debit":0,"credit":delta,"asset":rou.name,"line_description":"Lease liability remeasurement increase"}]
        elif delta<0:
            reduction=-delta
            lines=[{"account":lease.lease_liability_account,"debit":reduction,"credit":0,"asset":rou.name,"line_description":"Lease liability remeasurement decrease"}]
            if rou_adj<0: lines.append({"account":lease.rou_asset_account,"debit":0,"credit":-rou_adj,"asset":rou.name,"line_description":"Reduce right-of-use asset carrying amount"})
            if gain>0:
                gain_account=getattr(lease,"remeasurement_gain_account",None)
                if not gain_account: throw("Configure a Lease Remeasurement Gain Account on the lease before posting an excess liability reduction.")
                lines.append({"account":gain_account,"debit":0,"credit":gain,"asset":rou.name,"line_description":"Gain on lease remeasurement"})
        if lines:
            batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.effective_date,currency=lease.currency,exchange_rate=lease.exchange_rate or 1,lines=lines,posting_event="Original",remarks=self.reason_details,idempotency_key=f"lease-remeasurement:{self.name}")
            db_update(self,posting_batch=batch.name)
        if rou_adj:
            db_update(rou,acquisition_cost=M(D(rou.acquisition_cost)+rou_adj),carrying_amount=M(max(Decimal("0"),D(rou.carrying_amount)+rou_adj)))
        # Supersede only unpaid future schedule rows. Settled instalments remain immutable.
        from velora_erp.finance.doctype._utils import db_update_child
        old_rows=get_list("Fixed Asset Lease Payment",filters={"parent":lease.name,"parenttype":"Fixed Asset Lease","parentfield":"payments"},fields=["name","due_date","payment_status"],limit=10000,ignore_permissions=True)
        for old in old_rows:
            if old.get("payment_status")!="Paid": db_update_child("Fixed Asset Lease Payment",old["name"],payment_status="Superseded")
        # Rebuild the amortisation profile from the modification effective date using exact day fractions.
        opening=D(self.remeasured_liability); previous=date.fromisoformat(str(self.effective_date)[:10]); annual=D(self.discount_rate)/Decimal("100")
        for idx,payment in enumerate(self.payments,1):
            due=date.fromisoformat(str(payment.due_date)[:10]); days=max(0,(due-previous).days)
            interest=M(opening*((Decimal("1")+annual)**(D(days)/Decimal("365.25"))-Decimal("1")))
            principal=D(payment.payment_amount)-interest
            if principal<=0: throw(f"Revised lease instalment {idx} does not cover its interest component.")
            closing=M(opening-principal)
            if idx==len(self.payments):
                if abs(closing)>Decimal("0.01"): throw("Revised payment schedule does not fully amortise the remeasured lease liability.")
                principal=opening; interest=D(payment.payment_amount)-principal; closing=Decimal("0.00")
            child=new_doc("Fixed Asset Lease Payment",parent=lease.name,parenttype="Fixed Asset Lease",parentfield="payments",idx=len(old_rows)+idx,due_date=payment.due_date,payment_amount=payment.payment_amount,payment_status="Scheduled",opening_liability=opening,interest_expense=interest,principal_reduction=principal,closing_liability=closing)
            child.insert(ignore_permissions=True); opening=closing; previous=due
        lease_updates={"lease_liability_balance":self.remeasured_liability,"discount_rate":self.discount_rate}
        if self.modification_reason=="Change in Lease Term":
            lease_updates["lease_end_date"]=self.revised_lease_end_date
            remaining_months=max(1,(int(str(self.revised_lease_end_date)[:4])-int(str(self.effective_date)[:4]))*12+int(str(self.revised_lease_end_date)[5:7])-int(str(self.effective_date)[5:7]))
            elapsed_months=max(0,(int(str(self.effective_date)[:4])-int(str(lease.lease_start_date)[:4]))*12+int(str(self.effective_date)[5:7])-int(str(lease.lease_start_date)[5:7]))
            db_update(rou,useful_life_months=max(1,elapsed_months+remaining_months))
        db_update(lease,**lease_updates)
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(rou,"Lease Modification",self.effective_date,self.doctype,self.name,from_values={"carrying_amount":str(D(rou.carrying_amount)-rou_adj)},to_values={"carrying_amount":str(D(rou.carrying_amount)),"lease_liability":str(self.remeasured_liability)},reason=self.reason_details)
