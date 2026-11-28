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
    b = post_financial_transaction(source_doctype=doc.doctype, source_name=doc.name, posting_date=posting_date, currency=currency, exchange_rate=rate or 1, lines=lines, posting_event="Original", remarks=remarks, idempotency_key=f"{doc.doctype.lower().replace(' ','-')}:{doc.name}:{event.lower()}")
    return _persist(doc,b)

def lease_pv(payments, annual_rate, frequency, timing="Arrears"):
    months={"Monthly":1,"Quarterly":3,"Half-yearly":6,"Yearly":12}.get(frequency)
    if not months: throw("Unsupported lease payment frequency.")
    rate=(D(annual_rate)/Decimal("100"))*Decimal(months)/Decimal("12")
    pv=Decimal("0")
    for i,p in enumerate(payments,1):
        amt=D(p.payment_amount)
        if amt<=0: throw(f"Lease payment {i} must be greater than zero.")
        exponent = i if timing != "In Advance" else i-1
        pv+=amt/((Decimal("1")+rate)**exponent)
    return pv.quantize(CENT,rounding=ROUND_HALF_UP)
class FixedAssetLease(Document):
    def validate(self):
        _approval(self)
        if self.lease_type != "Lease In (Lessee)": throw("This release supports lessee-side IFRS 16 lease recognition. Lessor accounting requires a separate finance/operating lease module.")
        if str(self.lease_end_date)<=str(self.lease_start_date): throw("Lease End Date must be after Commencement Date.")
        if not self.payments: throw("At least one lease payment is required.")
        if D(self.discount_rate)<0 or D(self.exchange_rate)<=0: throw("Discount Rate cannot be negative and Exchange Rate must be positive.")
        previous=None
        for i,p in enumerate(self.payments,1):
            if str(p.due_date)<str(self.lease_start_date) or str(p.due_date)>str(self.lease_end_date): throw(f"Lease payment {i} must fall within the lease term.")
            if previous and str(p.due_date)<=str(previous): throw("Lease payment dates must be strictly increasing.")
            previous=p.due_date
        self.present_value=lease_pv(self.payments,self.discount_rate,self.payment_frequency,self.payment_timing or "Arrears")
        rate=(D(self.discount_rate)/Decimal("100"))*Decimal({"Monthly":1,"Quarterly":3,"Half-yearly":6,"Yearly":12}[self.payment_frequency])/Decimal("12")
        opening=D(self.present_value)
        for i,p in enumerate(self.payments,1):
            interest=Decimal("0") if (self.payment_timing=="In Advance" and i==1) else (opening*rate).quantize(CENT,rounding=ROUND_HALF_UP)
            principal=D(p.payment_amount)-interest
            if principal<=0: throw(f"Lease payment {i} does not cover its interest component.")
            closing=opening-principal
            if i==len(self.payments):
                # The final instalment must extinguish the remaining liability within one cent.
                if abs(closing)>CENT: throw("Lease payment schedule does not fully amortise the lease liability. Review payment amounts, dates and discount rate.")
                principal=opening; interest=D(p.payment_amount)-principal; closing=Decimal("0")
            p.opening_liability=opening; p.interest_expense=interest; p.principal_reduction=principal; p.closing_liability=closing
            opening=closing
        _account(self.rou_asset_account,["Asset"]); _account(self.lease_liability_account,["Liability"])
        if self.remeasurement_gain_account: _account(self.remeasurement_gain_account,["Income"])
        _account(self.interest_expense_account,["Expense"]); _account(self.accumulated_depreciation_account,["Asset"]); _account(self.depreciation_expense_account,["Expense"])
        if not self.asset_category: throw("Asset Category is required for the right-of-use asset.")
        category=get_doc("Fixed Asset Category",self.asset_category,ignore_permissions=True)
        if category.disabled: throw("The selected Fixed Asset Category is disabled.")
    def before_submit(self): _approved(self)
    def on_submit(self):
        amount=D(self.present_value)
        category=get_doc("Fixed Asset Category",self.asset_category,ignore_permissions=True)
        useful_life=max(1,((int(str(self.lease_end_date)[:4])-int(str(self.lease_start_date)[:4]))*12 + int(str(self.lease_end_date)[5:7])-int(str(self.lease_start_date)[5:7]) - (1 if int(str(self.lease_end_date)[8:10]) < int(str(self.lease_start_date)[8:10]) else 0)))
        asset=new_doc("Fixed Asset",asset_name=self.asset_name,asset_category=self.asset_category,
            acquisition_date=self.lease_start_date,acquisition_cost=amount,accumulated_depreciation=0,impairment_loss=0,
            revaluation_adjustment=0,residual_value=0,useful_life_months=useful_life,asset_account=self.rou_asset_account,
            accumulated_depreciation_account=self.accumulated_depreciation_account,depreciation_method="Straight Line",
            depreciation_expense_account=self.depreciation_expense_account,depreciation_start_date=self.lease_start_date,
            impairment_account=category.impairment_account,impairment_expense_account=category.impairment_expense_account,
            impairment_reversal_account=category.impairment_reversal_account,source_purchase=self.name,status="Leased")
        asset.flags.trusted_source=True
        asset.insert(ignore_permissions=True)
        lines=[
            {"account":self.rou_asset_account,"debit":amount,"credit":0,"asset":asset.name,"line_description":f"Right-of-use asset recognition {self.name}"},
            {"account":self.lease_liability_account,"debit":0,"credit":amount,"asset":asset.name,"line_description":f"Initial lease liability recognition {self.name}"},
        ]
        _safe_post(self,self.lease_start_date,self.currency,self.exchange_rate,lines,"Lease Commencement",f"Lease commencement {self.name}")
        db_update(self,lease_liability_balance=amount)
        from velora_erp.finance.asset_history import record_asset_history
        record_asset_history(asset, "Lease Commencement", self.lease_start_date, self.doctype, self.name,
            from_values={}, to_values={"status": "Leased", "acquisition_cost": str(amount),
            "carrying_amount": str(asset.carrying_amount)}, reason=f"Right-of-use asset recognised under lease {self.name}")
        self.right_of_use_asset=asset.name; db_update(self, right_of_use_asset=asset.name)
        self.status="Active"; db_update(self, status="Active")
