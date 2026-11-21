from decimal import Decimal
from velora import Document, throw, get_list
from velora_erp.finance.validation import row
class FixedAsset(Document):
    PROTECTED_FIELDS = (
        "asset_category", "acquisition_date", "acquisition_cost", "accumulated_depreciation",
        "impairment_loss", "revaluation_adjustment", "carrying_amount", "residual_value",
        "useful_life_months", "asset_account", "accumulated_depreciation_account", "source_purchase",
        "status", "revaluation_surplus", "revaluation_loss_balance", "depreciation_method",
        "depreciation_rate", "depreciation_expense_account", "depreciation_start_date",
        "total_units_of_production", "impairment_account", "impairment_expense_account",
        "impairment_reversal_account", "impairment_ceiling_carrying_amount", "impairment_against_revaluation_surplus",
        "impairment_charged_to_expense", "revaluation_surplus_account", "last_depreciation_date", "units_produced_to_date",
    )

    def before_insert(self):
        if not getattr(self.flags, "trusted_source", False):
            throw("Fixed Assets must be created through an approved Fixed Asset Purchase, Purchase Invoice or Fixed Asset Lease.")

    def validate(self):
        if self._old and not getattr(self.flags, "trusted_source_update", False):
            changed=[field for field in self.PROTECTED_FIELDS if getattr(self,field,None)!=self._old.get(field)]
            if changed: throw("Protected asset financial fields can only be changed through approved asset transactions: "+", ".join(changed))
        if not self.asset_name or not self.asset_category: throw("Asset Name and Asset Category are required.")
        category=row("Fixed Asset Category",self.asset_category,"name","disabled")
        if not category or category["disabled"]: throw("Select an active Fixed Asset Category.")
        if Decimal(str(self.acquisition_cost or 0))<=0: throw("Acquisition Cost must be greater than zero.")
        gross=Decimal(str(self.acquisition_cost or 0))+Decimal(str(self.revaluation_adjustment or 0))
        if Decimal(str(self.accumulated_depreciation or 0))+Decimal(str(self.impairment_loss or 0))>gross: throw("Accumulated depreciation and impairment cannot exceed revalued gross carrying amount.")
        if Decimal(str(self.accumulated_depreciation or 0)) > max(Decimal("0"), gross-Decimal(str(self.residual_value or 0))): throw("Accumulated depreciation cannot reduce the asset below its residual value.")
        if Decimal(str(self.residual_value or 0))>Decimal(str(self.acquisition_cost or 0)): throw("Residual Value cannot exceed Acquisition Cost.")
        if int(self.useful_life_months or 0)<=0: throw("Useful Life must be greater than zero.")
        self.carrying_amount=Decimal("0") if self.status == "Disposed" else Decimal(str(self.acquisition_cost or 0))+Decimal(str(self.revaluation_adjustment or 0))-Decimal(str(self.accumulated_depreciation or 0))-Decimal(str(self.impairment_loss or 0))
        if self.carrying_amount<0: throw("Carrying Amount cannot be negative.")
        for account in (self.asset_account,self.accumulated_depreciation_account):
            a=row("Account",account,"name","disabled","root_type")
            if not a or a["disabled"] or a["root_type"]!="Asset": throw(f"Select an active Asset account: {account}.")
        if not self.depreciation_method:
            self.depreciation_method = "Straight Line"
        if not self.depreciation_start_date: self.depreciation_start_date = self.acquisition_date
        if self.depreciation_method == "Reducing Balance" and not (Decimal(str(self.depreciation_rate or 0)) > 0 and Decimal(str(self.depreciation_rate or 0)) <= 100):
            throw("Reducing Balance Rate must be greater than 0 and not exceed 100%.")
        if self.depreciation_method == "Units of Production" and Decimal(str(self.total_units_of_production or 0)) <= 0:
            throw("Estimated Total Production Units must be greater than zero for Units of Production depreciation.")
        if self.depreciation_expense_account:
            dep = row("Account", self.depreciation_expense_account, "name", "disabled", "root_type")
            if not dep or dep["disabled"] or dep["root_type"] != "Expense": throw("Depreciation Expense Account must be an active Expense account.")
        for account, root in ((self.impairment_account, "Asset"), (self.impairment_expense_account, "Expense"), (self.impairment_reversal_account, "Income")):
            if account:
                a = row("Account", account, "name", "disabled", "root_type")
                if not a or a["disabled"] or a["root_type"] != root: throw(f"Impairment account {account} must be an active {root} account.")
        if self.cost_centre:
            cc=row("Cost Centre",self.cost_centre,"name","disabled","is_group")
            if not cc or cc["disabled"] or cc["is_group"]: throw("Select an active posting Cost Centre.")
        if self.revaluation_surplus_account:
            reserve=row("Account",self.revaluation_surplus_account,"name","disabled","root_type")
            if not reserve or reserve["disabled"] or reserve["root_type"]!="Equity": throw("Revaluation Surplus Account must be an active Equity account.")
        if self.name and self._old and not getattr(self.flags,"trusted_source_update",False):
            stored=get_list("Fixed Asset Component",filters={"parent":self.name,"parenttype":"Fixed Asset","parentfield":"components"},fields=["component_code","component_name","acquisition_cost","residual_value","useful_life_months","depreciation_method","depreciation_rate","depreciation_start_date","depreciation_expense_account","accumulated_depreciation_account","total_units_of_production"],limit=10000,ignore_permissions=True)
            incoming=[{"component_code":c.component_code,"component_name":c.component_name,"acquisition_cost":c.acquisition_cost,"residual_value":c.residual_value,"useful_life_months":c.useful_life_months,"depreciation_method":c.depreciation_method,"depreciation_rate":c.depreciation_rate,"depreciation_start_date":c.depreciation_start_date,"depreciation_expense_account":c.depreciation_expense_account,"accumulated_depreciation_account":c.accumulated_depreciation_account,"total_units_of_production":c.total_units_of_production} for c in (self.components or [])]
            normal=lambda rows: sorted([{k:(str(v)[:10] if k=="depreciation_start_date" and v else str(v or "")) for k,v in r.items()} for r in rows],key=lambda r:r["component_code"])
            if normal(stored)!=normal(incoming): throw("Asset component definitions are protected after acquisition. Use an approved component adjustment transaction.")
        component_total=Decimal("0")
        seen_components=set()
        for component in (self.components or []):
            if component.component_code in seen_components: throw(f"Duplicate asset component code: {component.component_code}.")
            seen_components.add(component.component_code)
            cost=Decimal(str(component.acquisition_cost or 0)); residual=Decimal(str(component.residual_value or 0))
            if cost<=0 or residual<0 or residual>cost: throw(f"Component {component.component_code}: enter a positive cost and a residual value not exceeding cost.")
            if int(component.useful_life_months or 0)<=0: throw(f"Component {component.component_code}: useful life must be greater than zero.")
            if component.depreciation_method=="Reducing Balance" and not (0 < Decimal(str(component.depreciation_rate or 0)) <= 100): throw(f"Component {component.component_code}: reducing balance rate must be greater than zero and not exceed 100%.")
            if component.depreciation_method=="Units of Production" and Decimal(str(component.total_units_of_production or 0))<=0: throw(f"Component {component.component_code}: estimated total production units must be greater than zero.")
            if not component.depreciation_start_date: throw(f"Component {component.component_code}: depreciation start date is required.")
            if component.status not in (None,"Active","Disposed"): throw(f"Component {component.component_code}: select a valid component status.")
            if component.status != "Disposed":
                if not component.carrying_amount: component.carrying_amount=cost
                component_total+=cost
        if component_total and abs(component_total-Decimal(str(self.acquisition_cost or 0)))>Decimal("0.01"): throw("For component accounting, component costs must reconcile to the asset acquisition cost. Include a residual component for any uncomponentised amount.")
        if component_total and abs(sum((Decimal(str(c.residual_value or 0)) for c in (self.components or []) if c.status != "Disposed"),Decimal("0"))-Decimal(str(self.residual_value or 0)))>Decimal("0.01"): throw("Component residual values must reconcile to the asset residual value.")
    def before_delete(self):
        throw("Fixed Asset register records are retained for audit and cannot be deleted. Use Fixed Asset Disposal.")
