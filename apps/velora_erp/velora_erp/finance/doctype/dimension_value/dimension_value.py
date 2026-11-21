from velora import Document, throw
from velora_erp.finance.validation import assert_parent, assert_no_children


class DimensionValue(Document):
    def validate(self):
        self.value_code = (self.value_code or "").strip().upper()
        self.value_name = (self.value_name or "").strip()
        if not self.value_code or not self.value_name or not self.dimension:
            throw("Dimension, value code and value name are required")
        from velora_erp.finance.validation import row
        dimension = row("Accounting Dimension", self.dimension, "name", "value_source", "disabled")
        if not dimension:
            throw("Select a valid Accounting Dimension")
        if dimension["disabled"]:
            throw("Values cannot be added to a disabled Accounting Dimension")
        if dimension["value_source"] != "Dimension Values":
            throw("Dimension Values can only be created for dimensions using the Dimension Values source")
        from sqlalchemy import select
        from velora import db
        from velora.db.tables import get_table
        table = get_table("Dimension Value")
        with db.transaction() as conn:
            duplicate = conn.execute(select(table.c.name).where(
                table.c.dimension == self.dimension, table.c.value_code == self.value_code,
                table.c.name != (self.name or "")
            ).limit(1)).first()
        if duplicate:
            throw(f"Value code {self.value_code} is already used in this dimension by {duplicate[0]}")
        if self.parent_value:
            parent = row("Dimension Value", self.parent_value, "name", "dimension", "is_group")
            if not parent or parent["dimension"] != self.dimension:
                throw("Parent value must belong to the same Accounting Dimension")
            assert_parent("Dimension Value", self.parent_value, self_name=self.name or self.value_code, group_field="is_group")

    def before_delete(self):
        assert_no_children("Dimension Value", "parent_value", self.name, "Dimension value")
