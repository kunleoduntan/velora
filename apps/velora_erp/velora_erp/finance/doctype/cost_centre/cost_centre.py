from velora import Document, throw
from velora_erp.finance.validation import assert_parent, assert_no_children


class CostCentre(Document):
    def validate(self):
        self.cost_centre_code = (self.cost_centre_code or "").strip().upper()
        self.cost_centre_name = (self.cost_centre_name or "").strip()
        if not self.cost_centre_code or not self.cost_centre_name:
            throw("Cost centre code and name are required")
        if self.parent_cost_centre:
            assert_parent("Cost Centre", self.parent_cost_centre, self_name=self.name or self.cost_centre_code, group_field="is_group")

    def before_delete(self):
        assert_no_children("Cost Centre", "parent_cost_centre", self.name, "Cost centre")
