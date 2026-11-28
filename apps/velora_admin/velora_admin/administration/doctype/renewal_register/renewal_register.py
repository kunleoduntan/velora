"""Universal administrative renewal register."""
from datetime import date


def renewal_state(expiry_date, today=None):
    """Return state and days-to-expiry for an expiry date."""
    if not expiry_date:
        return {"state": "No Expiry Date", "days_remaining": None}
    today = today or date.today()
    expiry = expiry_date if isinstance(expiry_date, date) else date.fromisoformat(str(expiry_date)[:10])
    days = (expiry - today).days
    if days < 0:
        state = "Expired"
    elif days == 0:
        state = "Expires Today"
    else:
        state = "Upcoming" if days > 0 else "Expired"
    return {"state": state, "days_remaining": days}


def renewal_alert_due(expiry_date, lead_days, today=None):
    """True when the item is within configured lead time or overdue."""
    if not expiry_date:
        return False
    today = today or date.today()
    expiry = expiry_date if isinstance(expiry_date, date) else date.fromisoformat(str(expiry_date)[:10])
    return (expiry - today).days <= int(lead_days or 0)
