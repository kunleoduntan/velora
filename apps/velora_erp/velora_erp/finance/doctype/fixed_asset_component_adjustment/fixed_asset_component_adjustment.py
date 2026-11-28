from decimal import Decimal, ROUND_HALF_UP
from velora import Document, throw, get_doc, new_doc
from velora_erp.finance.engine import post_financial_transaction
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved, finance_settings
from velora_erp.finance.validation import row
from velora_erp.finance.doctype._utils import db_update, db_update_child

D = lambda v: Decimal(str(v if v not in (None, "") else 0))
M = lambda v: D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
CENT = Decimal("0.01")


def _account(name, root):
    a = row("Account", name, "name", "root_type", "disabled") if name else None
    if not a or a["disabled"] or a["root_type"] != root:
        throw(f"Configure an active {root} account for this component adjustment.")
    return a


def _component(asset, reference):
    matches = [c for c in (asset.components or []) if c.name == reference]
    if len(matches) != 1:
        throw("The selected component row does not belong to this asset.")
    c = matches[0]
    if c.status != "Active":
        throw("Only an active component can be adjusted.")
    return c


def tracked_component_impairment(component):
    reserve=D(component.impairment_against_revaluation_surplus)
    pnl=D(component.impairment_charged_to_expense)
    total=D(component.impairment_loss)
    if reserve+pnl<total:
        pnl+=total-reserve-pnl  # unallocated legacy component impairment is assumed to have been charged to P&L
    if reserve+pnl>total:
        throw("Component impairment allocation tracking exceeds its recognised impairment. Reconcile before reversal.")
    return reserve,pnl


def _sync_parent(asset):
    components = [c for c in (asset.components or []) if c.status != "Disposed"]
    cost = sum((D(c.acquisition_cost) for c in components), Decimal("0"))
    accum = sum((D(c.accumulated_depreciation) for c in components), Decimal("0"))
    impairment = sum((D(c.impairment_loss) for c in components), Decimal("0"))
    revaluation = sum((D(c.revaluation_adjustment) for c in components), Decimal("0"))
    residual = sum((D(c.residual_value) for c in components), Decimal("0"))
    surplus = sum((D(c.revaluation_surplus) for c in components), Decimal("0"))
    revaluation_loss = sum((D(c.revaluation_loss_balance) for c in components), Decimal("0"))
    reserve_track = sum((D(c.impairment_against_revaluation_surplus) for c in components), Decimal("0"))
    pnl_track = sum((D(c.impairment_charged_to_expense) for c in components), Decimal("0"))
    ceiling = sum((D(c.impairment_ceiling_carrying_amount) for c in components), Decimal("0"))
    carrying = sum((D(c.carrying_amount) for c in components), Decimal("0"))
    db_update(asset, acquisition_cost=M(cost), accumulated_depreciation=M(accum), impairment_loss=M(impairment),
              revaluation_adjustment=M(revaluation), residual_value=M(residual), revaluation_surplus=M(surplus),
              revaluation_loss_balance=M(revaluation_loss), impairment_against_revaluation_surplus=M(reserve_track),
              impairment_charged_to_expense=M(pnl_track), impairment_ceiling_carrying_amount=M(ceiling),
              carrying_amount=M(carrying))


class FixedAssetComponentAdjustment(Document):
    def validate(self):
        validate_approval_transition(self)
        asset = get_doc("Fixed Asset", self.asset, ignore_permissions=True)
        if asset.status not in ("Active", "Leased"):
            throw("Select an active fixed asset.")
        if not self.reason or not self.adjustment_date:
            throw("Adjustment Date and supporting Reason are required.")
        if self.adjustment_type == "Add Component":
            if D(self.acquisition_cost) <= 0 or D(self.residual_value) < 0 or D(self.residual_value) > D(self.acquisition_cost):
                throw("A component addition requires positive cost and a residual value between zero and cost.")
            if int(self.useful_life_months or 0) <= 0:
                throw("Component useful life must be greater than zero.")
            if not self.depreciation_start_date:
                throw("Depreciation Start Date is required for a new component.")
            if any(c.component_code == self.component_code for c in (asset.components or [])):
                throw("Component Code must be unique within the fixed asset.")
            _account(asset.asset_account, "Asset")
            offset = row("Account", self.funding_account, "name", "root_type", "disabled") if self.funding_account else None
            if not offset or offset["disabled"] or offset["root_type"] not in ("Asset", "Liability", "Equity"):
                throw("Capitalisation Funding Account must be an active Asset, Liability or Equity account.")
            self.adjustment_amount = M(self.acquisition_cost)
            self.new_carrying_amount = M(self.acquisition_cost)
            return
        component = _component(asset, self.component_reference)
        if component.component_code != self.component_code:
            throw("Component Code does not match the selected component row.")
        current = D(component.carrying_amount)
        self.new_carrying_amount = current
        if self.adjustment_type == "Retire Component":
            if D(self.proceeds) < 0: throw("Retirement proceeds cannot be negative.")
            if D(self.proceeds) > 0:
                _account(self.proceeds_account, "Asset")
            if D(self.proceeds) - current > 0: _account(self.gain_account, "Income")
            elif D(self.proceeds) - current < 0: _account(self.loss_account, "Expense")
            if D(component.impairment_loss) > 0:
                category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                _account(self.impairment_account or asset.impairment_account or category.impairment_account, "Asset")
            if len([c for c in (asset.components or []) if c.status != "Disposed"]) <= 1:
                throw("The final active component cannot be retired separately. Use the full Fixed Asset Disposal workflow.")
            self.adjustment_amount = current
        elif self.adjustment_type == "Partially Dispose Component":
            percent=D(self.disposal_percentage)
            if percent<=0 or percent>=100: throw("Partial component disposal percentage must be greater than zero and less than 100%.")
            if D(self.proceeds)<0: throw("Disposal proceeds cannot be negative.")
            if D(self.proceeds)>0: _account(self.proceeds_account,"Asset")
            fraction=percent/Decimal("100")
            gross_removed=M((D(component.acquisition_cost)+D(component.revaluation_adjustment))*fraction)
            accum_removed=M(D(component.accumulated_depreciation)*fraction)
            impairment_removed=M(D(component.impairment_loss)*fraction)
            carrying_removed=M(gross_removed-accum_removed-impairment_removed)
            difference=M(D(self.proceeds)-carrying_removed)
            if difference>0: _account(self.gain_account,"Income")
            elif difference<0: _account(self.loss_account,"Expense")
            if D(component.impairment_loss)>0:
                category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                _account(self.impairment_account or asset.impairment_account or category.impairment_account,"Asset")
            if D(component.revaluation_surplus)>0:
                category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                _account(asset.revaluation_surplus_account or category.revaluation_surplus_account,"Equity")
                _account(self.revaluation_surplus_transfer_account,"Equity")
            if component.depreciation_method=="Units of Production":
                if D(self.revised_total_units_of_production)<=D(component.units_produced_to_date):
                    throw("Enter a revised estimated total production capacity greater than units already produced for the remaining component.")
            self.adjustment_amount=carrying_removed
            self.new_carrying_amount=M(current-carrying_removed)
        elif self.adjustment_type == "Impair Component":
            amount = M(self.adjustment_amount)
            if amount <= 0 or amount > current: throw("Component impairment must be positive and cannot exceed carrying amount.")
            category = get_doc("Fixed Asset Category", asset.asset_category, ignore_permissions=True)
            reserve = min(amount, D(component.revaluation_surplus))
            expense = M(amount - reserve)
            _account(self.impairment_account or asset.impairment_account or category.impairment_account, "Asset")
            if reserve > 0: _account(self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account, "Equity")
            if expense > 0: _account(self.impairment_expense_account or asset.impairment_expense_account or category.impairment_expense_account, "Expense")
            self.new_carrying_amount = M(current - amount)
        elif self.adjustment_type == "Reverse Component Impairment":
            reserve_tracked, pnl_tracked = tracked_component_impairment(component)
            ceiling = D(component.impairment_ceiling_carrying_amount)
            maximum = min(D(component.impairment_loss), max(Decimal("0"), ceiling-current))
            amount = M(self.adjustment_amount)
            if amount <= 0 or amount > maximum: throw(f"Reversal exceeds the component impairment or no-impairment carrying amount ceiling ({M(maximum)}).")
            pnl = min(amount, pnl_tracked); reserve = M(amount-pnl)
            category = get_doc("Fixed Asset Category", asset.asset_category, ignore_permissions=True)
            _account(self.impairment_account or asset.impairment_account or category.impairment_account, "Asset")
            if pnl > 0: _account(self.impairment_reversal_account or asset.impairment_reversal_account or category.impairment_reversal_account, "Income")
            if reserve > 0: _account(self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account, "Equity")
            self.new_carrying_amount = M(current + amount)
        elif self.adjustment_type == "Revalue Component":
            target = M(self.new_carrying_amount if self.new_carrying_amount is not None else self.adjustment_amount)
            delta = M(target-current)
            if target <= 0 or delta == 0: throw("New component carrying amount must be positive and different from the current amount.")
            category = get_doc("Fixed Asset Category", asset.asset_category, ignore_permissions=True)
            if delta > 0:
                reversal = min(delta, D(component.revaluation_loss_balance))
                if reversal > 0: _account(self.revaluation_gain_account, "Income")
                if delta-reversal > 0: _account(self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account, "Equity")
            else:
                reserve = min(-delta, D(component.revaluation_surplus))
                if reserve > 0: _account(self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account, "Equity")
                if -delta-reserve > 0: _account(self.revaluation_loss_account, "Expense")
            self.adjustment_amount = delta
        else:
            throw("Unsupported component adjustment type.")

    def before_submit(self):
        ensure_approved(self, required=True)
        if self.posting_batch: throw("This component adjustment has already been posted.")

    def on_submit(self):
        asset = get_doc("Fixed Asset", self.asset, ignore_permissions=True)
        lines = []
        dimensions = {"asset": asset.name, "cost_centre": asset.cost_centre or None, "business_unit": asset.business_unit or None}
        if self.adjustment_type == "Add Component":
            cost = M(self.acquisition_cost)
            lines = [{"account": asset.asset_account, "debit": cost, "credit": 0, "line_description": f"Capitalise component {self.component_code}", **dimensions},
                     {"account": self.funding_account, "debit": 0, "credit": cost, "line_description": f"Funding for component {self.component_code}", **dimensions}]
            if not (asset.components or []):
                baseline = new_doc("Fixed Asset Component", parent=asset.name, parenttype="Fixed Asset", parentfield="components", idx=1,
                    component_code="LEGACY-BASE", component_name="Existing Asset Base", acquisition_cost=asset.acquisition_cost,
                    residual_value=asset.residual_value, useful_life_months=asset.useful_life_months,
                    depreciation_method=asset.depreciation_method or "Straight Line", depreciation_rate=asset.depreciation_rate,
                    depreciation_start_date=asset.depreciation_start_date or asset.acquisition_date,
                    depreciation_expense_account=asset.depreciation_expense_account,
                    accumulated_depreciation_account=asset.accumulated_depreciation_account,
                    carrying_amount=asset.carrying_amount, accumulated_depreciation=asset.accumulated_depreciation,
                    impairment_loss=asset.impairment_loss, revaluation_adjustment=asset.revaluation_adjustment,
                    revaluation_surplus=asset.revaluation_surplus, revaluation_loss_balance=asset.revaluation_loss_balance,
                    impairment_ceiling_carrying_amount=asset.impairment_ceiling_carrying_amount,
                    impairment_against_revaluation_surplus=asset.impairment_against_revaluation_surplus,
                    impairment_charged_to_expense=asset.impairment_charged_to_expense,
                    total_units_of_production=asset.total_units_of_production, units_produced_to_date=asset.units_produced_to_date,
                    last_depreciation_date=asset.last_depreciation_date, status="Active")
                baseline.insert(ignore_permissions=True)
            child = new_doc("Fixed Asset Component", parent=asset.name, parenttype="Fixed Asset", parentfield="components", idx=(2 if not (asset.components or []) else len(asset.components or [])+1),
                component_code=self.component_code, component_name=self.component_name, acquisition_cost=cost, residual_value=self.residual_value,
                useful_life_months=self.useful_life_months, depreciation_method=self.depreciation_method or "Straight Line",
                depreciation_rate=self.depreciation_rate, depreciation_start_date=self.depreciation_start_date,
                depreciation_expense_account=asset.depreciation_expense_account, accumulated_depreciation_account=asset.accumulated_depreciation_account,
                carrying_amount=cost, accumulated_depreciation=0, impairment_loss=0, revaluation_adjustment=0, revaluation_surplus=0,
                impairment_ceiling_carrying_amount=0, impairment_against_revaluation_surplus=0, impairment_charged_to_expense=0,
                revaluation_loss_balance=0, status="Active")
            child.insert(ignore_permissions=True)
        else:
            component = _component(asset, self.component_reference)
            cost = D(component.acquisition_cost); accum = D(component.accumulated_depreciation); impairment = D(component.impairment_loss)
            contra = component.accumulated_depreciation_account or asset.accumulated_depreciation_account
            if self.adjustment_type == "Retire Component":
                if accum > 0: lines.append({"account": contra, "debit": accum, "credit": 0, "line_description": f"Clear component depreciation {self.component_code}", **dimensions})
                if impairment > 0:
                    category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                    lines.append({"account": self.impairment_account or asset.impairment_account or category.impairment_account, "debit": impairment, "credit": 0, "line_description": f"Clear component impairment {self.component_code}", **dimensions})
                if D(self.proceeds) > 0: lines.append({"account": self.proceeds_account, "debit": self.proceeds, "credit": 0, "line_description": f"Component retirement proceeds {self.component_code}", **dimensions})
                reserve_balance=D(component.revaluation_surplus)
                if reserve_balance>0:
                    category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                    reserve_account=asset.revaluation_surplus_account or category.revaluation_surplus_account
                    _account(reserve_account,"Equity"); _account(self.revaluation_surplus_transfer_account,"Equity")
                    lines.append({"account":reserve_account,"debit":reserve_balance,"credit":0,"line_description":"Transfer component revaluation surplus on retirement",**dimensions})
                    lines.append({"account":self.revaluation_surplus_transfer_account,"debit":0,"credit":reserve_balance,"line_description":"Transfer component revaluation surplus to retained earnings",**dimensions})
                gross = cost + D(component.revaluation_adjustment)
                lines.append({"account": asset.asset_account, "debit": 0, "credit": gross, "line_description": f"Derecognise component {self.component_code}", **dimensions})
                difference = D(self.proceeds) - D(component.carrying_amount)
                if difference > 0: lines.append({"account": self.gain_account, "debit": 0, "credit": difference, "line_description": f"Gain on component retirement {self.component_code}", **dimensions})
                elif difference < 0: lines.append({"account": self.loss_account, "debit": -difference, "credit": 0, "line_description": f"Loss on component retirement {self.component_code}", **dimensions})
                db_update_child("Fixed Asset Component", component.name, status="Disposed", carrying_amount=0, retirement_date=self.adjustment_date, retirement_reference=self.name)
            elif self.adjustment_type == "Partially Dispose Component":
                fraction=D(self.disposal_percentage)/Decimal("100")
                remaining=Decimal("1")-fraction
                cost_remaining=M(cost*remaining)
                revaluation_remaining=M(D(component.revaluation_adjustment)*remaining)
                gross_remaining=M(cost_remaining+revaluation_remaining)
                gross=M(cost+D(component.revaluation_adjustment)-gross_remaining)
                accum_remaining=M(accum*remaining); accum_removed=M(accum-accum_remaining)
                impairment_remaining=M(impairment*remaining); impairment_removed=M(impairment-impairment_remaining)
                carrying_removed=M(gross-accum_removed-impairment_removed)
                proceeds=M(self.proceeds)
                reserve_remaining=M(D(component.revaluation_surplus)*remaining)
                reserve_balance=M(D(component.revaluation_surplus)-reserve_remaining)
                if accum_removed>0: lines.append({"account":contra,"debit":accum_removed,"credit":0,"line_description":f"Clear partial component depreciation {self.component_code}",**dimensions})
                if impairment_removed>0:
                    category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                    lines.append({"account":self.impairment_account or asset.impairment_account or category.impairment_account,"debit":impairment_removed,"credit":0,"line_description":f"Clear partial component impairment {self.component_code}",**dimensions})
                if proceeds>0: lines.append({"account":self.proceeds_account,"debit":proceeds,"credit":0,"line_description":f"Partial component disposal proceeds {self.component_code}",**dimensions})
                if reserve_balance>0:
                    category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                    reserve_account=asset.revaluation_surplus_account or category.revaluation_surplus_account
                    _account(reserve_account,"Equity"); _account(self.revaluation_surplus_transfer_account,"Equity")
                    lines.append({"account":reserve_account,"debit":reserve_balance,"credit":0,"line_description":"Transfer partial component revaluation surplus",**dimensions})
                    lines.append({"account":self.revaluation_surplus_transfer_account,"debit":0,"credit":reserve_balance,"line_description":"Transfer partial component revaluation surplus to retained earnings",**dimensions})
                lines.append({"account":asset.asset_account,"debit":0,"credit":gross,"line_description":f"Derecognise partial component cost {self.component_code}",**dimensions})
                difference=M(proceeds-carrying_removed)
                if difference>0: lines.append({"account":self.gain_account,"debit":0,"credit":difference,"line_description":"Gain on partial component disposal",**dimensions})
                elif difference<0: lines.append({"account":self.loss_account,"debit":-difference,"credit":0,"line_description":"Loss on partial component disposal",**dimensions})
                db_update_child("Fixed Asset Component",component.name,
                    acquisition_cost=cost_remaining, residual_value=M(D(component.residual_value)*remaining),
                    accumulated_depreciation=accum_remaining, impairment_loss=impairment_remaining,
                    revaluation_adjustment=revaluation_remaining,
                    carrying_amount=M(gross_remaining-accum_remaining-impairment_remaining),
                    revaluation_surplus=reserve_remaining,
                    revaluation_loss_balance=M(D(component.revaluation_loss_balance)*remaining),
                    impairment_ceiling_carrying_amount=M(D(component.impairment_ceiling_carrying_amount)*remaining),
                    impairment_against_revaluation_surplus=M(D(component.impairment_against_revaluation_surplus)*remaining),
                    impairment_charged_to_expense=M(D(component.impairment_charged_to_expense)*remaining),
                    total_units_of_production=(self.revised_total_units_of_production if component.depreciation_method=="Units of Production" else component.total_units_of_production))
            elif self.adjustment_type == "Impair Component":
                amount = M(self.adjustment_amount); category = get_doc("Fixed Asset Category", asset.asset_category, ignore_permissions=True)
                reserve = min(amount, D(component.revaluation_surplus)); expense = M(amount-reserve)
                if reserve > 0: lines.append({"account": self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account, "debit": reserve, "credit": 0, "line_description": "Component impairment against revaluation surplus", **dimensions})
                if expense > 0: lines.append({"account": self.impairment_expense_account or asset.impairment_expense_account or category.impairment_expense_account, "debit": expense, "credit": 0, "line_description": "Component impairment expense", **dimensions})
                lines.append({"account": self.impairment_account or asset.impairment_account or category.impairment_account, "debit": 0, "credit": amount, "line_description": "Accumulated component impairment", **dimensions})
                db_update_child("Fixed Asset Component", component.name, impairment_loss=M(impairment+amount), carrying_amount=M(D(component.carrying_amount)-amount), impairment_ceiling_carrying_amount=(component.impairment_ceiling_carrying_amount or component.carrying_amount), revaluation_surplus=M(D(component.revaluation_surplus)-reserve), impairment_against_revaluation_surplus=M(D(component.impairment_against_revaluation_surplus)+reserve), impairment_charged_to_expense=M(D(component.impairment_charged_to_expense)+expense))
            elif self.adjustment_type == "Reverse Component Impairment":
                amount=M(self.adjustment_amount); reserve_tracked,pnl_tracked=tracked_component_impairment(component); pnl=min(amount,pnl_tracked); reserve=M(amount-pnl); category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                lines.append({"account":self.impairment_account or asset.impairment_account or category.impairment_account,"debit":amount,"credit":0,"line_description":"Reverse accumulated component impairment",**dimensions})
                if pnl>0: lines.append({"account":self.impairment_reversal_account or asset.impairment_reversal_account or category.impairment_reversal_account,"debit":0,"credit":pnl,"line_description":"Component impairment reversal through profit or loss",**dimensions})
                if reserve>0: lines.append({"account":self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account,"debit":0,"credit":reserve,"line_description":"Restore component revaluation surplus",**dimensions})
                db_update_child("Fixed Asset Component",component.name,impairment_loss=M(impairment-amount),carrying_amount=M(D(component.carrying_amount)+amount),impairment_against_revaluation_surplus=M(reserve_tracked-reserve),impairment_charged_to_expense=M(pnl_tracked-pnl),revaluation_surplus=M(D(component.revaluation_surplus)+reserve))
            elif self.adjustment_type == "Revalue Component":
                delta=M(D(self.new_carrying_amount)-D(component.carrying_amount)); category=get_doc("Fixed Asset Category",asset.asset_category,ignore_permissions=True)
                if delta>0:
                    reversal=min(delta,D(component.revaluation_loss_balance)); surplus=M(delta-reversal)
                    lines.append({"account":asset.asset_account,"debit":delta,"credit":0,"line_description":"Component revaluation increase",**dimensions})
                    if reversal>0: lines.append({"account":self.revaluation_gain_account,"debit":0,"credit":reversal,"line_description":"Reversal of prior component revaluation loss",**dimensions})
                    if surplus>0: lines.append({"account":self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account,"debit":0,"credit":surplus,"line_description":"Component revaluation surplus",**dimensions})
                    db_update_child("Fixed Asset Component",component.name,revaluation_adjustment=M(D(component.revaluation_adjustment)+delta),revaluation_loss_balance=M(D(component.revaluation_loss_balance)-reversal),revaluation_surplus=M(D(component.revaluation_surplus)+surplus),carrying_amount=M(D(component.carrying_amount)+delta))
                else:
                    amount=-delta; reserve=min(amount,D(component.revaluation_surplus)); loss=M(amount-reserve)
                    if reserve>0: lines.append({"account":self.revaluation_surplus_account or asset.revaluation_surplus_account or category.revaluation_surplus_account,"debit":reserve,"credit":0,"line_description":"Release component revaluation surplus",**dimensions})
                    if loss>0: lines.append({"account":self.revaluation_loss_account,"debit":loss,"credit":0,"line_description":"Component revaluation loss",**dimensions})
                    lines.append({"account":asset.asset_account,"debit":0,"credit":amount,"line_description":"Component revaluation decrease",**dimensions})
                    db_update_child("Fixed Asset Component",component.name,revaluation_adjustment=M(D(component.revaluation_adjustment)-amount),revaluation_surplus=M(D(component.revaluation_surplus)-reserve),revaluation_loss_balance=M(D(component.revaluation_loss_balance)+loss),carrying_amount=M(D(component.carrying_amount)-amount))
        settings=finance_settings()
        batch=post_financial_transaction(source_doctype=self.doctype,source_name=self.name,posting_date=self.adjustment_date,currency=settings["base_currency"],exchange_rate=1,lines=lines,posting_event="Original",remarks=self.reason,idempotency_key=f"asset-component-adjustment:{self.name}")
        db_update(self,posting_batch=batch.name)
        asset=get_doc("Fixed Asset",self.asset,ignore_permissions=True)
        _sync_parent(asset)

