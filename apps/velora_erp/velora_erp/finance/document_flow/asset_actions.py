"""Actions taken from a Fixed Asset: revalue, dispose, impair (or reverse), transfer, adjust a component.

Each action is its own approvable document (it posts, it has an audit trail, it can be cancelled and amended), so the asset
does not change itself. The action opens that document NEW AND UNSAVED, filled from the asset: nothing is created until the
user presses Save, so an abandoned action leaves no draft behind."""
from __future__ import annotations

from datetime import date

from velora import get_doc, throw

ACTIONS = {
    "Fixed Asset Revaluation": ("Active", "Leased"),
    "Fixed Asset Disposal": ("Active",),
    "Fixed Asset Impairment": ("Active", "Leased"),
    "Fixed Asset Transfer": ("Active", "Leased"),
    "Fixed Asset Component Adjustment": ("Active", "Leased"),
}


def _first(*values):
    return next((v for v in values if v), None)


def prefill(asset_name: str, target: str) -> dict:
    if target not in ACTIONS:
        throw(f"{target} cannot be started from a Fixed Asset.")
    asset = get_doc("Fixed Asset", asset_name)                 # the user's own read permission applies
    if asset.status not in ACTIONS[target]:
        throw(f"Fixed Asset {asset.name} is {asset.status}; {target} needs an asset that is {' or '.join(ACTIONS[target])}.")
    category = get_doc("Fixed Asset Category", asset.asset_category, ignore_permissions=True) if asset.asset_category else None
    cat = lambda f: getattr(category, f, None) if category else None
    today = date.today().isoformat()
    values: dict = {"asset": asset.name}
    if target == "Fixed Asset Revaluation":
        values.update(revaluation_date=today, previous_carrying_amount=asset.carrying_amount,
                      revaluation_surplus_account=_first(asset.revaluation_surplus_account, cat("revaluation_surplus_account")))
    elif target == "Fixed Asset Disposal":
        values.update(disposal_date=today, carrying_amount=asset.carrying_amount, asset_account=asset.asset_account,
                      accumulated_depreciation_account=asset.accumulated_depreciation_account,
                      impairment_account=_first(asset.impairment_account, cat("impairment_account")) if asset.impairment_loss else None)
    elif target == "Fixed Asset Impairment":
        values.update(assessment_date=today, action="Reverse Impairment" if asset.impairment_loss else "Recognise Impairment", carrying_amount_before=asset.carrying_amount,
                      impairment_account=_first(asset.impairment_account, cat("impairment_account")),
                      impairment_expense_account=_first(asset.impairment_expense_account, cat("impairment_expense_account")),
                      impairment_reversal_account=_first(asset.impairment_reversal_account, cat("impairment_reversal_account")),
                      revaluation_surplus_account=_first(asset.revaluation_surplus_account, cat("revaluation_surplus_account")))
        if not asset.impairment_loss:
            values["action"] = "Recognise Impairment"
    elif target == "Fixed Asset Transfer":
        values.update(transfer_date=today, from_location=asset.location, from_cost_centre=asset.cost_centre, from_business_unit=asset.business_unit)
    elif target == "Fixed Asset Component Adjustment":
        values.update(adjustment_date=today)
    return {"prefill": True, "doctype": target, "values": {k: v for k, v in values.items() if v not in (None, "")}, "source_doctype": "Fixed Asset", "source_document": asset.name}
