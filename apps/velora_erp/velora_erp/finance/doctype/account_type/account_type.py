from velora import Document, throw, db
from velora.db.tables import get_table
from sqlalchemy import select
from velora_erp.finance.validation import assert_no_children


class AccountType(Document):
    def validate(self):
        self.type_code = (self.type_code or "").strip().upper()
        self.type_name = (self.type_name or "").strip()
        if not self.type_code or not self.type_name:
            throw("Account type code and name are required")
        if self.root_type not in ("Asset", "Liability", "Equity", "Income", "Expense"):
            throw("Select a valid financial class")
        if self.normal_balance not in ("Debit", "Credit"):
            throw("Select a valid normal balance")
        if self._old and (self._old.get("root_type") != self.root_type or self._old.get("normal_balance") != self.normal_balance):
            accounts = get_table("Account")
            with db.transaction() as conn:
                used = conn.execute(select(accounts.c.name).where(accounts.c.account_type == self.name).limit(1)).first()
            if used:
                throw("This Account Type is already assigned to accounts; its financial class and normal balance cannot be changed")

    def before_delete(self):
        if self.is_system_type:
            throw("System-defined account types cannot be deleted; disable them instead")
        assert_no_children("Account", "account_type", self.name, "Account type")
