"""Investment settings now live on the Investments tab of Finance Settings (one place for the company's financial policy).

`get_settings()` keeps returning the short keys the investment code has always used."""
from __future__ import annotations

from velora import get_doc, get_list

DEFAULTS = {
    "auto_accrue": 0, "maturity_alert_days": 30, "wht_treatment": "Tax credit (asset)", "default_wht_rate": 10,
    "max_counterparty_percent": 25, "max_asset_group_percent": 70,
}
KEYS = (list(DEFAULTS) + ["bank_account", "interest_income_account", "dividend_income_account", "rental_income_account",
        "accrued_income_account", "deferred_income_account", "wht_receivable_account", "wht_expense_account",
        "realised_gain_loss_account", "unrealised_gain_loss_account", "fair_value_reserve_account", "investment_expense_account", "wht_tax_code"])


def field_for(key: str) -> str:
    return key if key.startswith("investment_") else f"investment_{key}"


def get_settings() -> dict:
    rows = get_list("Finance Settings", fields=["name"], limit=1, ignore_permissions=True)
    data = get_doc("Finance Settings", rows[0]["name"], ignore_permissions=True).as_dict() if rows else {}
    out = dict(DEFAULTS)
    for key in KEYS:
        value = data.get(field_for(key))
        if value not in (None, ""):
            out[key] = value
    return out
