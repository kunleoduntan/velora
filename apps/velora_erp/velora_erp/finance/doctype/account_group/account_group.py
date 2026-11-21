from velora import Document, throw, db
from sqlalchemy import select
from velora.db.tables import get_table
from velora_erp.finance.validation import assert_parent, assert_no_children


class AccountGroup(Document):
    def validate(self):
        self.group_code = (self.group_code or "").strip().upper()
        self.group_name = (self.group_name or "").strip()
        if not self.group_code or not self.group_name:
            throw("Group code and group name are required")
        if self.root_type not in ("Asset", "Liability", "Equity", "Income", "Expense"):
            throw("Select a valid financial class")
        if self.parent_group:
            parent = assert_parent("Account Group", self.parent_group, self_name=self.name or self.group_code, group_field="is_group", root_field="root_type", expected_root=self.root_type)
            if parent:
                self.root_type = parent["root_type"]
        if self._old and self._old.get("root_type") != self.root_type:
            accounts = get_table("Account")
            groups = get_table("Account Group")
            with db.transaction() as conn:
                account_used = conn.execute(select(accounts.c.name).where(accounts.c.account_group == self.name).limit(1)).first()
                child_used = conn.execute(select(groups.c.name).where(groups.c.parent_group == self.name).limit(1)).first()
            if account_used or child_used:
                throw("This Account Group is already in use; its financial class cannot be changed")

    def before_delete(self):
        assert_no_children("Account Group", "parent_group", self.name, "Account group")
        assert_no_children("Account", "account_group", self.name, "Account group")
