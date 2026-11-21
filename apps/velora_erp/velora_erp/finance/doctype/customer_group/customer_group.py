from velora import Document, get_list, throw
from velora_erp.finance.validation import row, assert_no_children


class CustomerGroup(Document):
    def validate(self):
        self.group_code = (self.group_code or "").strip().upper()
        self.group_name = (self.group_name or "").strip()
        if not self.group_code or not self.group_name:
            throw("Customer Group Code and Name are required.")
        margin = float(getattr(self, "selling_margin_percent", 0) or 0)
        if margin < 0:
            throw("Selling Margin cannot be negative.")
        if margin >= 100:
            settings = get_list("Inventory Settings", fields=["selling_price_basis"], limit=1, ignore_permissions=True)
            if settings and settings[0].get("selling_price_basis") == "Margin on Selling Price":
                throw("Selling Margin must be below 100% when using Margin on Selling Price.")
        if self.parent_group:
            parent = row("Customer Group", self.parent_group, "name", "is_group", "disabled")
            if not parent or parent["disabled"] or not parent["is_group"]:
                throw("Select an active parent Customer Group that allows subgroups.")
            seen = set()
            current = parent
            while current:
                if self.name and current["name"] == self.name:
                    throw("This parent would create a customer group hierarchy loop.")
                if current["name"] in seen:
                    throw("The existing customer group hierarchy contains a loop.")
                seen.add(current["name"])
                current = row("Customer Group", current.get("parent_group"), "name", "parent_group", "is_group", "disabled") if current.get("parent_group") else None

    def before_delete(self):
        assert_no_children("Customer Group", "parent_group", self.name, "Customer Group")
        assert_no_children("Customer", "customer_group", self.name, "Customer Group")
