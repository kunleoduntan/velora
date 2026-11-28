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
def money(v): return D(v).quantize(CENT,rounding=ROUND_HALF_UP)
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
def _validate_payment_account(purchase_type, account_name):
    if not account_name: throw("Bank / Cash Account is required for an immediate payment.")
    account=_account(account_name,["Asset"])
    if purchase_type=="Immediate Cash Payment" and account.get("account_type")!="CASH":
        throw("Immediate Cash Payment requires an active GL account configured with Account Type CASH.")
    if purchase_type=="Immediate Bank Payment" and account.get("account_type") not in ("BANK","CASH"):
        throw("Select an active Bank or Cash GL account.")
    return account
def _safe_post(doc, posting_date, currency, rate, lines, event, remarks):
    b = post_financial_transaction(source_doctype=doc.doctype, source_name=doc.name, posting_date=posting_date, currency=currency, exchange_rate=rate or 1, lines=lines, posting_event="Original", remarks=remarks, idempotency_key=f"{doc.doctype.lower().replace(' ','-')}:{doc.name}:{event.lower()}")
    return _persist(doc,b)

class FixedAssetPurchase(Document):
    def validate(self):
        _approval(self)
        if not self.items or not self.purchase_date: throw("Purchase Date and asset lines are required.")
        if str(self.purchase_date)>str(date.today()): throw("Purchase Date cannot be in the future.")
        request = None
        if self.request_reference:
            request=get_doc("Fixed Asset Request",self.request_reference,ignore_permissions=True)
            if request.docstatus!=1 or request.status!="Approved" or request.converted_purchase: throw("Only an approved, unconverted Fixed Asset Request can be linked.")
        if self.purchase_type=="Supplier Credit":
            if not self.supplier or not self.supplier_payable_account: throw("Supplier and Supplier Payable Account are required for Supplier Credit.")
            _account(self.supplier_payable_account,["Liability"])
            supplier=row("Supplier",self.supplier,"name","disabled","control_account")
            if not supplier or supplier["disabled"] or supplier["control_account"]!=self.supplier_payable_account: throw("Supplier Payable Account must match the selected supplier's configured control account.")
        elif self.purchase_type in ("Immediate Bank Payment", "Immediate Cash Payment"):
            _validate_payment_account(self.purchase_type,self.bank_account)
        else: throw("Select a valid Purchase Type.")
        total=Decimal("0")
        item_names=[l.asset_name for l in self.items]
        if len(item_names)!=len(set(item_names)): throw("Asset Line Name must be unique within a Fixed Asset Purchase when component rows are used.")
        if any(c.asset_line_name not in item_names for c in (self.asset_components or [])): throw("Every component row must reference an existing Asset Line Name.")
        for i,l in enumerate(self.items,1):
            if D(l.unit_cost)<=0 or int(l.quantity or 0)<=0: throw(f"Asset line {i}: quantity and unit cost must be positive.")
            _account(l.asset_account,["Asset"])
            category=get_doc("Fixed Asset Category",l.asset_category,ignore_permissions=True)
            if category.disabled: throw(f"Asset line {i}: category is disabled.")
            if int(l.useful_life_months or 0)<=0: throw(f"Asset line {i}: useful life must be positive.")
            l.depreciation_method = l.depreciation_method or category.default_depreciation_method or "Straight Line"
            if l.depreciation_method == "Reducing Balance" and not (0 < float(l.depreciation_rate or category.default_reducing_balance_rate or 0) <= 100): throw(f"Asset line {i}: configure a reducing balance rate between 0 and 100%.")
            if l.depreciation_method == "Units of Production" and D(l.total_units_of_production) <= 0: throw(f"Asset line {i}: estimated total production units must be greater than zero.")
            if D(l.residual_value)>D(l.unit_cost): throw(f"Asset line {i}: residual value per asset cannot exceed unit cost.")
            component_rows=[c for c in (self.asset_components or []) if c.asset_line_name==l.asset_name]
            if component_rows:
                if abs(sum((D(c.acquisition_cost) for c in component_rows),Decimal("0"))-D(l.unit_cost))>CENT: throw(f"Asset line {i}: component costs must reconcile to unit cost.")
                if abs(sum((D(c.residual_value) for c in component_rows),Decimal("0"))-D(l.residual_value))>CENT: throw(f"Asset line {i}: component residual values must reconcile to asset residual value.")
            total+=D(l.unit_cost)*int(l.quantity)
        self.total_cost=total
        if D(self.exchange_rate)<=0: throw("Exchange Rate must be greater than zero.")
    def before_submit(self): _approved(self)
    def on_submit(self):
        # Create each asset identity before posting so acquisition ledger rows can
        # carry the exact asset reference. All work remains in the source submit transaction.
        prepared=[]
        for line in self.items:
            category=get_doc("Fixed Asset Category",line.asset_category,ignore_permissions=True)
            quantity=int(line.quantity)
            base_unit_cost=(D(line.unit_cost)*D(self.exchange_rate)).quantize(CENT,rounding=ROUND_HALF_UP)
            base_residual=(D(line.residual_value)*D(self.exchange_rate)).quantize(CENT,rounding=ROUND_HALF_UP)
            for index in range(quantity):
                name=line.asset_name if quantity==1 else f"{line.asset_name} {index+1}"
                asset=new_doc("Fixed Asset",asset_name=name,asset_category=line.asset_category,
                    acquisition_date=self.purchase_date,acquisition_cost=base_unit_cost,accumulated_depreciation=0,
                    impairment_loss=0,revaluation_adjustment=0,residual_value=base_residual,
                    useful_life_months=line.useful_life_months,asset_account=line.asset_account,
                    accumulated_depreciation_account=category.accumulated_depreciation_account,
                    depreciation_method=line.depreciation_method,depreciation_rate=line.depreciation_rate or category.default_reducing_balance_rate,
                    depreciation_expense_account=category.depreciation_expense_account,depreciation_start_date=self.purchase_date,
                    total_units_of_production=line.total_units_of_production,impairment_account=category.impairment_account,
                    impairment_expense_account=category.impairment_expense_account,impairment_reversal_account=category.impairment_reversal_account,
                    cost_centre=line.cost_centre,business_unit=line.business_unit,location=line.location,
                    source_purchase=self.name,status="Active",
                    components=[{"component_code":c.component_code,"component_name":c.component_name,"acquisition_cost":money(D(c.acquisition_cost)*D(self.exchange_rate)),"residual_value":money(D(c.residual_value)*D(self.exchange_rate)),"useful_life_months":c.useful_life_months,"depreciation_method":c.depreciation_method,"depreciation_rate":c.depreciation_rate,"depreciation_start_date":c.depreciation_start_date or self.purchase_date,"carrying_amount":money(D(c.acquisition_cost)*D(self.exchange_rate)),"accumulated_depreciation":0,"depreciation_expense_account":c.depreciation_expense_account or category.depreciation_expense_account,"accumulated_depreciation_account":c.accumulated_depreciation_account or category.accumulated_depreciation_account,"total_units_of_production":c.total_units_of_production,"units_produced_to_date":0} for c in (self.asset_components or []) if c.asset_line_name==line.asset_name])
                asset.flags.trusted_source=True
                asset.insert(ignore_permissions=True)
                prepared.append((line,asset))

        lines=[]
        counter=self.supplier_payable_account if self.purchase_type=="Supplier Credit" else self.bank_account
        for line,asset in prepared:
            common={"cost_centre":line.cost_centre or None,"business_unit":line.business_unit or None,
                    "line_description":f"Fixed asset acquisition: {line.asset_name}","asset":asset.name}
            lines += [{"account":line.asset_account,"debit":D(line.unit_cost),"credit":0,**common},
                      {"account":counter,"debit":0,"credit":D(line.unit_cost),
                       "party_type":"Supplier" if self.purchase_type=="Supplier Credit" else None,
                       "party":self.supplier if self.purchase_type=="Supplier Credit" else None,**common}]
        _safe_post(self,self.purchase_date,self.currency,self.exchange_rate,lines,"Asset Acquisition",f"Fixed Asset Purchase {self.name}")
        created=[asset.name for _,asset in prepared]
        from velora_erp.finance.asset_history import record_asset_history
        for line,asset in prepared:
            record_asset_history(asset,"Acquisition",self.purchase_date,self.doctype,self.name,from_values={},
                to_values={"status":"Active","acquisition_cost":str(asset.acquisition_cost),
                           "carrying_amount":str(asset.carrying_amount)},reason=f"Asset acquired through {self.name}")
        db_update(self,status="Posted",created_assets=", ".join(created))
        if self.request_reference:
            request=get_doc("Fixed Asset Request",self.request_reference,ignore_permissions=True)
            db_update(request,status="Converted",converted_purchase=self.name)

