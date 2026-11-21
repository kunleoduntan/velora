from velora import Document, throw, get_doc
from velora_erp.finance.source_documents import validate_approval_transition, ensure_approved
from velora_erp.finance.validation import row
from velora_erp.finance.doctype._utils import db_update



def assignment_changes(current, destination):
    """Return only changed asset assignment fields; values are normalized to empty strings."""
    return {key: (current.get(key) or "", destination.get(key) or "")
            for key in ("location", "cost_centre", "business_unit")
            if (current.get(key) or "") != (destination.get(key) or "")}


def _active_cost_centre(name):
    if not name:
        return
    cc = row("Cost Centre", name, "name", "disabled", "is_group")
    if not cc or cc["disabled"] or cc["is_group"]:
        throw(f"Select an active posting Cost Centre: {name}.")


def _active_business_unit(name):
    if not name:
        return
    unit = row("Business Unit", name, "name", "disabled")
    if not unit or unit["disabled"]:
        throw(f"Select an active Business Unit: {name}.")


class FixedAssetTransfer(Document):
    def validate(self):
        validate_approval_transition(self)
        asset = get_doc("Fixed Asset", self.asset, ignore_permissions=True)
        if asset.status not in ("Active", "Leased"):
            throw("Only active owned or right-of-use assets can be transferred.")
        if str(self.transfer_date) < str(asset.acquisition_date):
            throw("Transfer Date cannot be before the asset Acquisition Date.")
        if asset.last_depreciation_date and str(self.transfer_date) <= str(asset.last_depreciation_date):
            throw("Transfer Date must be after the last depreciation date. Complete depreciation through the prior day before transferring the asset.")

        # The source values are always taken from the asset register, never trusted from the browser.
        self.from_location = asset.location or ""
        self.from_cost_centre = asset.cost_centre or ""
        self.from_business_unit = asset.business_unit or ""
        self.to_location = (self.to_location or "").strip()
        current = {"location": self.from_location, "cost_centre": self.from_cost_centre, "business_unit": self.from_business_unit}
        destination = {"location": self.to_location, "cost_centre": self.to_cost_centre, "business_unit": self.to_business_unit}
        if not assignment_changes(current, destination):
            throw("Change at least one location, cost centre or business unit assignment.")
        _active_cost_centre(self.to_cost_centre)
        _active_business_unit(self.to_business_unit)
        if not (self.reason or "").strip():
            throw("A reason for the asset transfer is required.")

    def before_submit(self):
        ensure_approved(self, required=True)

    def on_submit(self):
        asset = get_doc("Fixed Asset", self.asset, ignore_permissions=True)
        # Serialize transfers and reject stale requests rather than overwriting a newer movement.
        asset._lock_and_check()
        asset.reload()
        current = {
            "location": asset.location or "",
            "cost_centre": asset.cost_centre or "",
            "business_unit": asset.business_unit or "",
        }
        expected = {
            "location": self.from_location or "",
            "cost_centre": self.from_cost_centre or "",
            "business_unit": self.from_business_unit or "",
        }
        if current != expected:
            throw("The asset assignment changed after this transfer was prepared. Refresh the asset and create a new transfer.")
        destination = {
            "location": self.to_location or None,
            "cost_centre": self.to_cost_centre or None,
            "business_unit": self.to_business_unit or None,
        }
        db_update(asset, **destination)
        before = {k: v or None for k, v in current.items()}
        after = destination
        from velora_erp.finance.asset_history import record_asset_history
        history = record_asset_history(asset, "Transfer", self.transfer_date, self.doctype, self.name,
                                        from_values=before, to_values=after, reason=self.reason)
        db_update(self, history_record=history.name)

