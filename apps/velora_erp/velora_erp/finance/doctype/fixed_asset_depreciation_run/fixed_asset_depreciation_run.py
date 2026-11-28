from datetime import date, timedelta
from types import SimpleNamespace
from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc, get_list
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.doctype._utils import db_update, db_update_child
from velora_erp.finance.validation import row
CENT=Decimal("0.01")
D=lambda v: Decimal(str(v or 0))
def money(v): return D(v).quantize(CENT,rounding=ROUND_HALF_UP)
def days_between(start,end): return (date.fromisoformat(str(end)[:10])-date.fromisoformat(str(start)[:10])).days+1
def depreciation_amount(asset,category,period_days,units=0,elapsed_days=0):
    method=asset.depreciation_method or category.default_depreciation_method or "Straight Line"
    residual=D(asset.residual_value); opening=D(asset.carrying_amount); depreciable=max(Decimal("0"),opening-residual)
    if depreciable<=0: return Decimal("0.00")
    if method=="Straight Line":
        life_days=D(asset.useful_life_months)*Decimal("365.25")/Decimal("12")
        remaining=max(Decimal("0"),life_days-D(elapsed_days)); amount=depreciable*D(period_days)/remaining if remaining else Decimal("0")
    elif method=="Reducing Balance":
        rate=D(asset.depreciation_rate or category.default_reducing_balance_rate)
        if rate<=0 or rate>100: throw(f"Asset {asset.name}: configure a valid reducing balance rate.")
        amount=depreciable*rate/Decimal("100")*D(period_days)/Decimal("365.25")
    elif method=="Units of Production":
        total=D(asset.total_units_of_production); produced=D(units); to_date=D(getattr(asset,"units_produced_to_date",0))
        if total<=0 or produced<=0: throw(f"Asset {asset.name}: enter valid estimated and period production units.")
        remaining=max(Decimal("0"),total-to_date)
        if produced>remaining: throw(f"Asset {asset.name}: period production exceeds remaining estimated units.")
        amount=depreciable*produced/remaining if remaining else Decimal("0")
    else: throw(f"Unsupported depreciation method: {method}.")
    return min(depreciable,money(amount))

def _book_balance(asset_name, book_name):
    matches=get_list("Fixed Asset Book Balance",filters={"asset":asset_name,"depreciation_book":book_name},fields=["name"],limit=2,ignore_permissions=True)
    if len(matches)!=1: throw(f"Create exactly one Fixed Asset Book Balance for asset {asset_name} in book {book_name} before running a non-financial book.")
    return get_doc("Fixed Asset Book Balance",matches[0]["name"],ignore_permissions=True)

class FixedAssetDepreciationRun(Document):
    def validate(self):
        validate_approval_transition(self)
        if str(self.period_end)<str(self.period_start): throw("Period End cannot be before Period Start.")
        if str(self.posting_date)<str(self.period_end): throw("Posting Date cannot be before the depreciation period end.")
        if not self.lines: throw("Add at least one asset to the depreciation run.")
        book=None
        if not self.depreciation_book:
            defaults=get_list("Fixed Asset Depreciation Book",filters={"is_default":1,"disabled":0},fields=["name"],limit=2,ignore_permissions=True)
            if len(defaults)==1: self.depreciation_book=defaults[0]["name"]
        if self.depreciation_book:
            book=get_doc("Fixed Asset Depreciation Book",self.depreciation_book,ignore_permissions=True)
            if book.disabled: throw("Select an active depreciation book.")
            self.book_type=book.book_type
        else: self.book_type="Financial (Legacy)"
        seen=set(); total=Decimal("0.00")
        supplied_component_lines=list(self.component_lines or [])
        supplied_units={}
        for supplied in supplied_component_lines:
            key=(supplied.asset,supplied.component_code)
            if key in supplied_units: throw(f"Duplicate component depreciation input for {key[0]} / {key[1]}.")
            supplied_units[key]=D(supplied.units_produced)
        self.component_lines=[]
        for line in self.lines:
            if line.asset in seen: throw(f"Asset {line.asset} appears more than once in this depreciation run.")
            seen.add(line.asset); asset=get_doc("Fixed Asset",line.asset,ignore_permissions=True)
            if asset.status not in ("Active","Leased"): throw(f"Asset {asset.name} is not active or leased.")
            category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
            balance=None; calc=asset
            if book and book.book_type in ("Tax","Management"):
                balance=_book_balance(asset.name,book.name)
                calc=SimpleNamespace(name=asset.name,depreciation_method=balance.depreciation_method,acquisition_cost=balance.acquisition_cost,revaluation_adjustment=0,residual_value=balance.residual_value,carrying_amount=balance.carrying_amount,useful_life_months=balance.useful_life_months,depreciation_rate=balance.depreciation_rate,total_units_of_production=balance.total_units_of_production,units_produced_to_date=balance.units_produced_to_date,depreciation_start_date=balance.depreciation_start_date,last_depreciation_date=balance.last_depreciation_date)
                line.book_balance_reference=balance.name
            start_date=str(getattr(calc,"depreciation_start_date",None) or asset.depreciation_start_date or asset.acquisition_date)[:10]
            last_date=getattr(calc,"last_depreciation_date",None)
            if last_date:
                expected=(date.fromisoformat(str(last_date)[:10])+timedelta(days=1)).isoformat()
                if str(self.period_start)[:10]!=expected: throw(f"Asset {asset.name}: next depreciation period for this book must start on {expected}; periods cannot overlap or leave gaps.")
            elif str(self.period_start)[:10]>start_date: throw(f"Asset {asset.name}: first depreciation run must start on or before {start_date}; establish opening book balances for migrated assets.")
            start=max(str(self.period_start)[:10],start_date)
            if str(self.period_end)<start: throw(f"Depreciation period is before the depreciation start date for {asset.name}.")
            method=calc.depreciation_method or category.default_depreciation_method or "Straight Line"
            days=days_between(start,self.period_end); elapsed=max(0,days_between(start_date,start)-1)
            if asset.components and (not book or book.book_type == "Financial"):
                component_rows=[]; component_total=Decimal("0.00"); component_opening=Decimal("0.00")
                for component in asset.components:
                    if getattr(component,"status",None)=="Disposed": continue
                    comp_start=str(component.depreciation_start_date or asset.depreciation_start_date or asset.acquisition_date)[:10]
                    comp_last=component.last_depreciation_date
                    if comp_last:
                        expected_comp=(date.fromisoformat(str(comp_last)[:10])+timedelta(days=1)).isoformat()
                        if str(self.period_start)[:10]!=expected_comp: throw(f"Asset {asset.name}, component {component.component_code}: next depreciation period must start on {expected_comp}.")
                    elif str(self.period_start)[:10]>comp_start: throw(f"Asset {asset.name}, component {component.component_code}: first depreciation run must start on or before {comp_start}.")
                    comp_period_start=max(str(self.period_start)[:10],comp_start)
                    comp_days=days_between(comp_period_start,self.period_end)
                    comp_elapsed=max(0,days_between(comp_start,comp_period_start)-1)
                    comp_asset=SimpleNamespace(name=f"{asset.name}/{component.component_code}",depreciation_method=component.depreciation_method,acquisition_cost=component.acquisition_cost,revaluation_adjustment=component.revaluation_adjustment or 0,residual_value=component.residual_value,carrying_amount=component.carrying_amount or component.acquisition_cost,useful_life_months=component.useful_life_months,depreciation_rate=component.depreciation_rate,total_units_of_production=component.total_units_of_production,units_produced_to_date=component.units_produced_to_date)
                    comp_units=supplied_units.get((asset.name,component.component_code),Decimal("0"))
                    comp_amount=depreciation_amount(comp_asset,category,comp_days,comp_units,comp_elapsed)
                    ceiling_amount=Decimal("0.00")
                    if D(component.impairment_ceiling_carrying_amount)>0:
                        ceiling_asset=SimpleNamespace(**{**vars(comp_asset),"carrying_amount":D(component.impairment_ceiling_carrying_amount)})
                        ceiling_amount=depreciation_amount(ceiling_asset,category,comp_days,comp_units,comp_elapsed)
                    if comp_amount<=0: throw(f"No depreciation is due for component {component.component_code} of {asset.name}.")
                    exp_account=component.depreciation_expense_account or asset.depreciation_expense_account or category.depreciation_expense_account
                    contra_account=component.accumulated_depreciation_account or asset.accumulated_depreciation_account
                    exp=row("Account",exp_account,"name","disabled","root_type") if exp_account else None
                    contra=row("Account",contra_account,"name","disabled","root_type") if contra_account else None
                    if not exp or exp["disabled"] or exp["root_type"]!="Expense": throw(f"Component {component.component_code}: configure an active Depreciation Expense account.")
                    if not contra or contra["disabled"] or contra["root_type"]!="Asset": throw(f"Component {component.component_code}: configure an active Accumulated Depreciation account.")
                    opening_comp=D(component.carrying_amount or component.acquisition_cost); closing_comp=opening_comp-comp_amount
                    component_rows.append({"component_code":component.component_code,"units_produced":comp_units,"opening_carrying_amount":opening_comp,"depreciation_amount":comp_amount,"closing_carrying_amount":closing_comp,"expense_account":exp_account,"accumulated_depreciation_account":contra_account})
                    component_total+=comp_amount; component_opening+=opening_comp
                if not component_rows: throw(f"Asset {asset.name}: component accounting requires at least one component.")
                for component_row in component_rows:
                    self.append("component_lines",{"asset":asset.name,**component_row})
                line.depreciation_method="Component Based"; line.opening_carrying_amount=component_opening
                line.depreciation_amount=money(component_total); line.closing_carrying_amount=money(component_opening-component_total)
                line.expense_account=None; line.accumulated_depreciation_account=None
                line.book_type=book.book_type if book else "Financial (Legacy)"
                line.cost_centre=line.cost_centre or asset.cost_centre; line.business_unit=line.business_unit or asset.business_unit
                total+=component_total
                continue
            amount=depreciation_amount(calc,category,days,line.units_produced,elapsed)
            if amount<=0: throw(f"No depreciation is due for asset {asset.name} in this period.")
            expense=(balance.expense_account if balance else None) or asset.depreciation_expense_account or category.depreciation_expense_account
            contra=(balance.accumulated_depreciation_account if balance else None) or asset.accumulated_depreciation_account
            if not book or book.book_type=="Financial":
                if not expense: throw(f"Configure Depreciation Expense Account for asset {asset.name} or its category.")
                exp=row("Account",expense,"name","disabled","root_type"); acc=row("Account",contra,"name","disabled","root_type")
                if not exp or exp["disabled"] or exp["root_type"]!="Expense": throw(f"Depreciation expense account for {asset.name} must be an active Expense account.")
                if not acc or acc["disabled"] or acc["root_type"]!="Asset": throw(f"Accumulated depreciation account for {asset.name} must be an active Asset account.")
            line.depreciation_method=method; line.opening_carrying_amount=calc.carrying_amount
            line.depreciation_amount=amount; line.closing_carrying_amount=D(calc.carrying_amount)-amount
            line.expense_account=expense; line.accumulated_depreciation_account=contra
            line.book_type=book.book_type if book else "Financial (Legacy)"
            line.cost_centre=line.cost_centre or asset.cost_centre; line.business_unit=line.business_unit or asset.business_unit
            if line.cost_centre:
                cc=row("Cost Centre",line.cost_centre,"name","disabled","is_group")
                if not cc or cc["disabled"] or cc["is_group"]: throw(f"Asset {asset.name}: select an active posting Cost Centre.")
            if line.business_unit:
                bu=row("Business Unit",line.business_unit,"name","disabled")
                if not bu or bu["disabled"]: throw(f"Asset {asset.name}: select an active Business Unit.")
            total+=amount
        self.total_depreciation=money(total)
        # Component lines are generated during validation, after the framework's
        # initial child-link pass. Re-link once so their names/parent/idx are persisted.
        self._link_children()
    def before_submit(self): ensure_approved(self,required=True)
    def on_submit(self):
        book=get_doc("Fixed Asset Depreciation Book",self.depreciation_book,ignore_permissions=True) if self.depreciation_book else None
        is_nonposting=bool(book and book.book_type in ("Tax","Management"))
        if not is_nonposting:
            lines=[]
            for line in self.lines:
                component_rows=[c for c in (self.component_lines or []) if c.asset==line.asset]
                if component_rows:
                    for component_line in component_rows:
                        amount=D(component_line.depreciation_amount)
                        lines.extend([
                         {"account":component_line.expense_account,"debit":amount,"credit":0,"line_description":f"Depreciation {line.asset} component {component_line.component_code} for {self.period_start} to {self.period_end}","cost_centre":line.cost_centre or None,"business_unit":line.business_unit or None,"asset":line.asset},
                         {"account":component_line.accumulated_depreciation_account,"debit":0,"credit":amount,"line_description":f"Accumulated depreciation {line.asset} component {component_line.component_code}","cost_centre":line.cost_centre or None,"business_unit":line.business_unit or None,"asset":line.asset}])
                else:
                    amount=D(line.depreciation_amount)
                    lines.extend([
                     {"account":line.expense_account,"debit":amount,"credit":0,"line_description":f"Depreciation {line.asset} for {self.period_start} to {self.period_end}","cost_centre":line.cost_centre or None,"business_unit":line.business_unit or None,"asset":line.asset},
                     {"account":line.accumulated_depreciation_account,"debit":0,"credit":amount,"line_description":f"Accumulated depreciation {line.asset}","cost_centre":line.cost_centre or None,"business_unit":line.business_unit or None,"asset":line.asset}])
            settings=finance_settings()
            batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.posting_date,currency=settings["base_currency"],exchange_rate=1,lines=lines,posting_event="Original",remarks=self.remarks or f"Fixed asset depreciation {self.period_start} to {self.period_end}",idempotency_key=f"fixed-asset-depreciation:{self.name}")
            db_update(self,posting_batch=batch.name)
        for line in self.lines:
            asset=get_doc("Fixed Asset",line.asset,ignore_permissions=True)
            if is_nonposting:
                balance=get_doc("Fixed Asset Book Balance",line.book_balance_reference,ignore_permissions=True)
                db_update(balance,accumulated_depreciation=money(D(balance.accumulated_depreciation)+D(line.depreciation_amount)),carrying_amount=money(D(balance.carrying_amount)-D(line.depreciation_amount)),last_depreciation_date=self.period_end,units_produced_to_date=D(balance.units_produced_to_date)+D(line.units_produced))
                continue
            updates=dict(accumulated_depreciation=money(D(asset.accumulated_depreciation)+D(line.depreciation_amount)),carrying_amount=money(D(asset.carrying_amount)-D(line.depreciation_amount)),last_depreciation_date=self.period_end,units_produced_to_date=D(asset.units_produced_to_date)+D(line.units_produced))
            component_rows=[c for c in (self.component_lines or []) if c.asset==line.asset]
            if component_rows:
                for component_line in component_rows:
                    component=next(c for c in asset.components if c.component_code==component_line.component_code)
                    ceiling=D(component.impairment_ceiling_carrying_amount)
                    notional=Decimal("0.00")
                    if ceiling>0:
                        comp_start=str(component.depreciation_start_date or asset.depreciation_start_date or asset.acquisition_date)[:10]
                        comp_period_start=max(str(self.period_start)[:10],comp_start)
                        comp_days=days_between(comp_period_start,self.period_end)
                        comp_elapsed=max(0,days_between(comp_start,comp_period_start)-1)
                        ceiling_asset=SimpleNamespace(name=f"{asset.name}/{component.component_code}",depreciation_method=component.depreciation_method,acquisition_cost=component.acquisition_cost,revaluation_adjustment=component.revaluation_adjustment or 0,residual_value=component.residual_value,carrying_amount=ceiling,useful_life_months=component.useful_life_months,depreciation_rate=component.depreciation_rate,total_units_of_production=component.total_units_of_production,units_produced_to_date=component.units_produced_to_date)
                        notional=depreciation_amount(ceiling_asset,get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True),comp_days,D(component_line.units_produced),comp_elapsed)
                    db_update_child("Fixed Asset Component",component.name,accumulated_depreciation=money(D(component.accumulated_depreciation)+D(component_line.depreciation_amount)),carrying_amount=money(D(component.carrying_amount or component.acquisition_cost)-D(component_line.depreciation_amount)),impairment_ceiling_carrying_amount=(money(max(D(component.residual_value),ceiling-notional)) if ceiling>0 else component.impairment_ceiling_carrying_amount),last_depreciation_date=self.period_end,units_produced_to_date=D(component.units_produced_to_date)+D(component_line.units_produced))
                refreshed=get_doc("Fixed Asset",asset.name,ignore_permissions=True)
                updates["impairment_ceiling_carrying_amount"]=money(sum((D(c.impairment_ceiling_carrying_amount) for c in refreshed.components if c.status!="Disposed"),Decimal("0")))
            elif D(asset.impairment_ceiling_carrying_amount)>0:
                ceiling=D(asset.impairment_ceiling_carrying_amount)
                ceiling_calc=SimpleNamespace(name=asset.name,depreciation_method=calc.depreciation_method,acquisition_cost=calc.acquisition_cost,revaluation_adjustment=getattr(calc,"revaluation_adjustment",0),residual_value=calc.residual_value,carrying_amount=ceiling,useful_life_months=calc.useful_life_months,depreciation_rate=calc.depreciation_rate,total_units_of_production=calc.total_units_of_production,units_produced_to_date=calc.units_produced_to_date)
                notional=depreciation_amount(ceiling_calc,category,days,D(line.units_produced),elapsed)
                updates["impairment_ceiling_carrying_amount"]=money(max(D(asset.residual_value),ceiling-notional))
            db_update(asset,**updates)
            from velora_erp.finance.asset_history import record_asset_history
            record_asset_history(asset,"Depreciation",self.period_end,self.doctype,self.name,from_values={"carrying_amount":str(line.opening_carrying_amount)},to_values={"carrying_amount":str(line.closing_carrying_amount),"depreciation_amount":str(line.depreciation_amount)},reason=f"Financial book depreciation from {self.period_start} to {self.period_end}")
