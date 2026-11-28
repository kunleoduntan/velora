"""Project cost, forecast, contract and billing control calculations."""
from decimal import Decimal, InvalidOperation

def money(v, field):
    try: x=Decimal(str(v))
    except (InvalidOperation,TypeError,ValueError): raise ValueError(f"{field} must be numeric.")
    if not x.is_finite() or x<0: raise ValueError(f"{field} must be finite and non-negative.")
    return x

def cost_forecast(budget, actual, committed, estimate_to_complete, approved_changes=0, pending_changes=0):
    b,a,c,etc,ac,pc=[money(v,n) for v,n in [(budget,"budget"),(actual,"actual"),(committed,"committed"),(estimate_to_complete,"estimate_to_complete"),(approved_changes,"approved_changes"),(pending_changes,"pending_changes")]]
    revised=b+ac; eac=a+c+etc
    return {"original_budget":b,"approved_changes":ac,"revised_budget":revised,"actual_cost":a,"open_commitments":c,"estimate_to_complete":etc,"estimate_at_completion":eac,"variance_at_completion":revised-eac,"pending_changes_excluded":pc,"forecast_overrun":max(Decimal("0"),eac-revised)}

def validate_contract(contract):
    required=("contract_id","project_id","currency","start_date","end_date")
    missing=[k for k in required if not str(contract.get(k) or "").strip()]
    if missing: raise ValueError("Missing contract fields: "+", ".join(missing))
    if contract["end_date"]<contract["start_date"]: raise ValueError("Contract end date cannot precede start date.")
    value=money(contract.get("contract_value",0),"contract_value")
    retention=money(contract.get("retention_percent",0),"retention_percent")
    if retention>100: raise ValueError("Retention percentage cannot exceed 100.")
    return {"valid":True,"contract_value":value,"retention_percent":retention}

def billing_position(contract_value, approved_variations, billed_to_date, recognised_revenue, retention_percent=0):
    base,variations,billed,revenue=[money(v,n) for v,n in [(contract_value,"contract_value"),(approved_variations,"approved_variations"),(billed_to_date,"billed_to_date"),(recognised_revenue,"recognised_revenue")]]
    retention=money(retention_percent,"retention_percent")
    if retention>100: raise ValueError("retention_percent cannot exceed 100")
    revised=base+variations
    if billed>revised: raise ValueError("Billed to date cannot exceed revised contract value.")
    return {"revised_contract_value":revised,"billed_to_date":billed,"unbilled_contract_value":revised-billed,"recognised_revenue":revenue,"retention_amount":billed*retention/Decimal("100")}
