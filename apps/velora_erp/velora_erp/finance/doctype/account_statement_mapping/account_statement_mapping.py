from velora import Document, throw
from sqlalchemy import select, or_
from velora import db
from velora.db.tables import get_table


class AccountStatementMapping(Document):
    def validate(self):
        self.mapping_code = (self.mapping_code or "").strip().upper()
        if not self.mapping_code:
            throw("Mapping code is required")
        if self.mapping_basis == "Account":
            if not self.account or self.account_group:
                throw("Select exactly one Account for an Account mapping")
            account = get_table("Account")
            with db.transaction() as conn:
                target_account = conn.execute(select(account.c.name, account.c.disabled).where(account.c.name == self.account)).mappings().first()
            if not target_account or target_account["disabled"]:
                throw("Select an active Account")
        elif self.mapping_basis == "Account Group":
            if not self.account_group or self.account:
                throw("Select exactly one Account Group for an Account Group mapping")
            group = get_table("Account Group")
            with db.transaction() as conn:
                target_group = conn.execute(select(group.c.name, group.c.disabled).where(group.c.name == self.account_group)).mappings().first()
            if not target_group or target_group["disabled"]:
                throw("Select an active Account Group")
        else:
            throw("Select a valid mapping basis")
        row = get_table("Financial Statement Row")
        with db.transaction() as conn:
            target = conn.execute(select(row.c.name, row.c.row_type, row.c.disabled, row.c.statement_type).where(row.c.name == self.statement_row)).mappings().first()
        if not target or target["disabled"]:
            throw("Select an active Financial Statement Row")
        if target["row_type"] != "Account Summary":
            throw("Accounts can only be mapped to Account Summary rows")
        # Reject duplicate active mapping targets; the same account/group may have one mapping per statement row.
        table = get_table("Account Statement Mapping")
        row_table = get_table("Financial Statement Row")
        criteria = [table.c.name != (self.name or ""), or_(table.c.disabled.is_(None), table.c.disabled == 0)]
        criteria.append(table.c.account == self.account if self.mapping_basis == "Account" else table.c.account_group == self.account_group)
        with db.transaction() as conn:
            duplicate = conn.execute(
                select(table.c.name).join(row_table, table.c.statement_row == row_table.c.name)
                .where(*criteria, row_table.c.statement_type == target["statement_type"])
                .limit(1)
            ).first()
        if duplicate:
            throw(f"This account or account group is already mapped to the selected statement row by {duplicate[0]}")
