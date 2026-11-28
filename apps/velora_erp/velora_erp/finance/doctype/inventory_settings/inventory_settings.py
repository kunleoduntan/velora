from velora import Document, get_doc, get_list, throw
class InventorySettings(Document):
    def validate(self):
        margin_basis = getattr(self, "selling_price_basis", "Markup on Cost") or "Markup on Cost"
        if margin_basis not in {"Markup on Cost", "Margin on Selling Price"}:
            throw("Selling Price Basis must be Markup on Cost or Margin on Selling Price.")
        cost_basis = getattr(self, "selling_cost_basis", "Last Purchase Cost") or "Last Purchase Cost"
        from velora_erp.finance.pricing import COST_BASES
        if cost_basis == "Average of Last Purchases":      # the name 2.95.3 used for the quantity-weighted average
            self.selling_cost_basis = cost_basis = "Weighted Average of Last Purchases"
        if cost_basis not in COST_BASES:
            throw("Cost Used for Pricing must be one of: " + ", ".join(COST_BASES) + ".")
        if not 3 <= int(getattr(self, "purchases_to_average", 3) or 3) <= 5:
            throw("Purchases to Average must be between 3 and 5.")
        if float(getattr(self, "minimum_profit_percent", 0) or 0) < 0:
            throw("Minimum Profit cannot be negative.")
        if float(getattr(self, "default_selling_margin_percent", 0) or 0) < 0:
            throw("Default Selling Margin cannot be negative.")
        if margin_basis == "Margin on Selling Price":
            if float(getattr(self, "default_selling_margin_percent", 0) or 0) >= 100:
                throw("Default Selling Margin must be below 100% when using Margin on Selling Price.")
            for doctype, field in (("Inventory Item", "selling_margin_percent"), ("Customer Group", "selling_margin_percent")):
                rows = get_list(doctype, fields=["name", field], limit=100000, ignore_permissions=True)
                invalid = [row["name"] for row in rows if float(row.get(field) or 0) >= 100]
                if invalid:
                    throw(f"{doctype} {invalid[0]} has a selling margin of 100% or more. Reduce it before using Margin on Selling Price.")
        if float(getattr(self, "price_rounding_step", 0) or 0) < 0:
            throw("Price Rounding Step cannot be negative.")
        expected = {
            "default_inventory_asset_account": "Asset",
            "goods_received_not_invoiced_account": "Liability",
            "cost_of_goods_sold_account": "Expense",
            "stock_adjustment_gain_account": "Income",
            "stock_adjustment_loss_account": "Expense",
        }
        selected = []
        for field, root_type in expected.items():
            name = getattr(self, field, None)
            if not name: throw(f"{field.replace('_', ' ').title()} is required.")
            account = get_doc("Account", name)
            if account.disabled or account.root_type != root_type:
                throw(f"{field.replace('_', ' ').title()} must be an active {root_type} ledger account.")
            selected.append(name)
        variance = getattr(self, "purchase_price_variance_account", None)
        if variance:
            account = get_doc("Account", variance)
            if account.disabled or account.root_type != "Expense":
                throw("Purchase Price Variance Account must be an active Expense ledger account.")
            selected.append(variance)
        optional_accounts = {
            "opening_balance_clearing_account": {"Equity"},
            "stock_revaluation_gain_account": {"Income"},
            "stock_revaluation_loss_account": {"Expense"},
        }
        for field, roots in optional_accounts.items():
            name = getattr(self, field, None)
            if name:
                account = get_doc("Account", name)
                if account.disabled or account.root_type not in roots:
                    throw(f"{field.replace('_', ' ').title()} must be an active {' or '.join(sorted(roots))} account.")
                if field == "opening_balance_clearing_account":
                    selected.append(name)
        if len(set(selected)) != len(selected):
            throw("Inventory control, GRNI, COGS, adjustment and opening clearing accounts must be distinct.")
