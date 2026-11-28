"""Rules every fixed-asset action shares."""
from __future__ import annotations

from datetime import date, timedelta

from velora import throw


def _as_date(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def require_depreciation_up_to(asset, on_date, action: str) -> None:
    """IAS 16.55 and 16.68: depreciation runs until the asset is derecognised, and a revaluation restates a carrying amount that is current.
    So depreciation must have been posted to the end of the month before the action date; otherwise the missing depreciation
    would be hidden inside the gain or loss (disposal) or the surplus (revaluation)."""
    if not on_date or not getattr(asset, "depreciation_start_date", None):
        return
    if not (int(getattr(asset, "useful_life_months", 0) or 0) or float(getattr(asset, "depreciation_rate", 0) or 0) or float(getattr(asset, "total_units_of_production", 0) or 0)):
        return                                                                       # not depreciated (e.g. land)
    due_to = _as_date(on_date).replace(day=1) - timedelta(days=1)
    if _as_date(asset.depreciation_start_date) > due_to:
        return
    last = getattr(asset, "last_depreciation_date", None)
    if not last or _as_date(last) < due_to:
        throw(f"Run depreciation for {asset.name} up to {due_to.isoformat()} before the {action} (last posted: {last or 'never'}). "
              f"Depreciation continues until the asset leaves the books, so the {action} must start from an up-to-date carrying amount.")
