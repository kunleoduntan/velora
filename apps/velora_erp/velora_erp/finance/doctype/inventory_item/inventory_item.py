from velora import Document, get_doc, get_list, throw

def _ensure(doctype, key, value, **extra):
    """Create a missing Unit of Measure / Item Group so free typing never fails and the master stays complete."""
    from velora import db, new_doc
    if value and not db.exists(doctype, value):
        new_doc(doctype, **{key: value}, **extra).insert(ignore_permissions=True)


def _selling_price(item) -> float:
    """What the item sells for: the fixed price, or its cost plus the margin (using the Selling Price Basis in Inventory Settings)."""
    from velora_erp.finance.pricing import _settings, raw_price, round_price
    if getattr(item, "pricing_mode", "Margin Based") == "Fixed Price":
        return float(item.standard_selling_rate or 0)
    cost = float(item.standard_rate or 0) or float(getattr(item, "last_purchase_cost", 0) or 0)
    if cost <= 0:
        return 0.0
    s = _settings()
    raw = raw_price(cost, item.selling_margin_percent or 0, s.get("selling_price_basis") or "Markup on Cost")
    return float(round_price(raw, s.get("price_rounding_step", 0))) if raw is not None else 0.0


class InventoryItem(Document):
    def validate(self):
        if not self.is_stock_item:
            self.tracking_mode = "None"
            self.purchase_receipt_policy = "Follow Inventory Settings"
            if self.spread_over_periods:
                if int(self.spread_period_count or 0) < 2: throw("Spread over at least 2 periods.")
                if not self.prepaid_account: throw("Choose the Prepaid / Deferred Cost Account for a spread item.")
        else:
            self.spread_over_periods = 0
        if not self.item_name or not self.stock_uom:
            throw("Item Name and Stock Unit of Measure are required.")
        _ensure("Unit of Measure", "uom_name", self.stock_uom)
        if self.item_group: _ensure("Item Group", "group_name", self.item_group)
        for f in ("reorder_level", "reorder_qty", "maximum_stock_level"):
            if float(getattr(self, f, 0) or 0) < 0: throw(f"{f.replace('_', ' ').title()} cannot be negative.")
        if float(getattr(self, "maximum_stock_level", 0) or 0) and float(getattr(self, "reorder_level", 0) or 0) > float(self.maximum_stock_level): throw("The reorder level cannot be above the maximum stock level.")
        if self.tracking_mode not in {"None", "Serial Number", "Batch"}:
            throw("Invalid inventory tracking mode.")
        if getattr(self, "valuation_method", None) not in {"Moving Average", "FIFO", "Weighted Average"}:
            throw("Valuation Method must be Moving Average, FIFO or Weighted Average.")
        if float(self.standard_rate or 0) < 0:
            throw("Standard Cost Rate cannot be negative.")
        if getattr(self, "pricing_mode", "Margin Based") not in {"Margin Based", "Fixed Price"}:
            throw("Pricing Mode must be Margin Based or Fixed Price.")
        from velora_erp.finance.pricing import COST_BASES
        if getattr(self, "selling_cost_basis", None) == "Average of Last Purchases":
            self.selling_cost_basis = "Weighted Average of Last Purchases"
        if getattr(self, "selling_cost_basis", None) not in (None, "", "Follow Settings", *COST_BASES):
            throw("Cost Used for Pricing is not a valid choice.")
        margin = float(getattr(self, "selling_margin_percent", 0) or 0)
        if margin < 0:
            throw("Selling Margin cannot be negative.")
        if margin >= 100:
            settings = get_list("Inventory Settings", fields=["selling_price_basis"], limit=1, ignore_permissions=True)
            if settings and settings[0].get("selling_price_basis") == "Margin on Selling Price":
                throw("Selling Margin must be below 100% when using Margin on Selling Price.")
        if float(getattr(self, "standard_selling_rate", 0) or 0) < 0:
            throw("Standard Selling Rate cannot be negative.")
        if getattr(self, "pricing_mode", "Margin Based") == "Fixed Price" and float(getattr(self, "standard_selling_rate", 0) or 0) <= 0:
            throw("A positive Standard Selling Rate is required when Pricing Mode is Fixed Price.")
        self.calculated_selling_price = _selling_price(self)
        if self.stock_asset_account:
            account = get_doc("Account", self.stock_asset_account)
            if account.disabled or account.root_type != "Asset":
                throw("Inventory Asset Account Override must be an active Asset ledger account.")
        if not self.is_new():
            previous = get_doc("Inventory Item", self.name)
            if not getattr(self.flags, "cost_refresh", False):
                for field in ("last_purchase_cost", "last_purchase_date", "last_purchase_reference", "cost_source"):
                    if getattr(previous, field, None) != getattr(self, field, None):
                        throw(f"{field.replace('_', ' ').title()} is system-maintained from submitted purchasing and inventory records.")
            if previous.valuation_method != self.valuation_method:
                movements = get_list("Stock Ledger Record", filters={"item_code": self.name}, fields=["name"], limit=1, ignore_permissions=True)
                if movements:
                    throw("Valuation Method cannot be changed after stock movements exist. Use an approved valuation migration/revaluation process.")
