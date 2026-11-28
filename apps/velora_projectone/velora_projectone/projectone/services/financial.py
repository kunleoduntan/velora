from decimal import Decimal, InvalidOperation

def calculate_budget_position(approved_budget, actual_cost, open_commitments, pending_change=0):
    """Calculate remaining control budget; pending changes never increase authority."""
    vals={}
    for key,value in {"approved_budget":approved_budget,"actual_cost":actual_cost,"open_commitments":open_commitments,"pending_change":pending_change}.items():
        try: d=Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError): raise ValueError(f"{key} must be a valid number.")
        if not d.is_finite() or d < 0: raise ValueError(f"{key} must be finite and non-negative.")
        vals[key]=d
    committed=vals["actual_cost"]+vals["open_commitments"]
    return {**vals,"total_exposure":committed,"available_budget":vals["approved_budget"]-committed,"utilisation_ratio":committed/vals["approved_budget"] if vals["approved_budget"] else None,"pending_change_excluded":vals["pending_change"]}
