from velora import Document, throw
from velora_erp.finance.validation import row, assert_no_children


class SupplierGroup(Document):
    def validate(self):
        self.group_code = (self.group_code or "").strip().upper()
        self.group_name = (self.group_name or "").strip()
        if not self.group_code or not self.group_name:
            throw("Supplier Group Code and Name are required.")
        if self.parent_group:
            parent = row("Supplier Group", self.parent_group, "name", "is_group", "disabled")
            if not parent or parent["disabled"] or not parent["is_group"]:
                throw("Select an active parent Supplier Group that allows subgroups.")
            seen = set()
            current = parent
            while current:
                if self.name and current["name"] == self.name:
                    throw("This parent would create a supplier group hierarchy loop.")
                if current["name"] in seen:
                    throw("The existing supplier group hierarchy contains a loop.")
                seen.add(current["name"])
                current = row("Supplier Group", current.get("parent_group"), "name", "parent_group", "is_group", "disabled") if current.get("parent_group") else None

    def before_delete(self):
        assert_no_children("Supplier Group", "parent_group", self.name, "Supplier Group")
        assert_no_children("Supplier", "supplier_group", self.name, "Supplier Group")
