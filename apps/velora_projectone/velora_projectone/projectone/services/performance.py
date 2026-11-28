from decimal import Decimal, InvalidOperation

def _d(value, field):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid number.")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result

def calculate_earned_value(pv, ev, ac, bac=None):
    """Calculate standard EVM measures with explicit null ratios at zero denominators."""
    pv, ev, ac = _d(pv, "pv"), _d(ev, "ev"), _d(ac, "ac")
    if min(pv, ev, ac) < 0:
        raise ValueError("PV, EV and AC cannot be negative.")
    sv, cv = ev-pv, ev-ac
    spi = ev/pv if pv else None
    cpi = ev/ac if ac else None
    result = {"pv":pv,"ev":ev,"ac":ac,"sv":sv,"cv":cv,"spi":spi,"cpi":cpi}
    if bac is not None:
        bac = _d(bac, "bac")
        if bac < 0: raise ValueError("BAC cannot be negative.")
        result["bac"] = bac
        result["eac"] = bac/cpi if cpi and cpi > 0 else None
        result["etc"] = result["eac"]-ac if result["eac"] is not None else None
        result["vac"] = bac-result["eac"] if result["eac"] is not None else None
    return result
