from velora import Document, throw
from velora_erp.finance.validation import row


class Account(Document):
    def validate(self):
        self.account_code = (self.account_code or "").strip().upper()
        self.account_name = (self.account_name or "").strip()
        if not self.account_code or not self.account_name:
            throw("Account code and account name are required")
        group = row("Account Group", self.account_group, "name", "root_type", "disabled")
        if not group:
            throw("Select a valid account group")
        if group["disabled"]:
            throw("An account cannot be assigned to a disabled account group")
        account_type = row("Account Type", self.account_type, "name", "root_type", "normal_balance", "requires_party", "allows_control_account", "default_reconciliation", "disabled")
        if not account_type or account_type["disabled"]:
            throw("Select an active Account Type")
        if account_type["root_type"] != group["root_type"]:
            throw(f"Account Type {self.account_type} belongs to {account_type['root_type']}, not {group['root_type']}")
        self.root_type = group["root_type"]
        self.report_type = "Balance Sheet" if self.root_type in ("Asset", "Liability", "Equity") else "Profit and Loss"
        if not 0 <= float(self.tax_rate or 0) <= 100:
            throw("Default Tax Rate must be between 0 and 100 percent")
        self.normal_balance = account_type["normal_balance"]
        self.is_group = int(bool(self.is_group))
        if self.is_group:                       # a heading only adds up its sub-accounts: it carries none of the posting-account settings, whatever its type suggests
            self.is_control_account = 0
            self.control_account_type = None
            self.account_currency = None
        self.requires_party = 0 if self.is_group else int(bool(account_type["requires_party"]))
        # "Allow Reconciliation" starts from the Account Type (fetch_from) and follows it when the type changes; after that it is the user's choice.
        self.reconciliation_required = 0 if self.is_group else (int(bool(account_type["default_reconciliation"])) if self.reconciliation_required is None else int(bool(self.reconciliation_required)))
        if self.is_control_account and not account_type["allows_control_account"]:
            throw("This Account Type is not permitted to be a control account")
        if self.is_control_account and not self.control_account_type:
            throw("Select the purpose of this control account")
        if not self.is_control_account and self.control_account_type:
            throw("Control account purpose can only be set when Control Account is enabled")
        if self.account_currency:
            self.account_currency = self.account_currency.strip().upper()
            if len(self.account_currency) != 3 or not self.account_currency.isalpha():
                throw("Account currency must be a three-letter ISO currency code")

        self._validate_group()

    def _validate_group(self):
        """A group account is a heading: it adds up the accounts under it and nothing is posted to it. Posting accounts are the leaves."""
        from sqlalchemy import func, select
        from velora import db
        from velora.db.tables import get_table
        self.is_group = int(bool(self.is_group))
        if self.parent_account:
            if self.name and self.parent_account == self.name:
                throw("An account cannot be its own parent")
            parent = row("Account", self.parent_account, "name", "is_group", "root_type", "disabled", "parent_account")
            if not parent or not parent["is_group"]:
                throw(f"{self.parent_account} is not a group account. Tick Is Group on it first, then list this account under it.")
            if parent["root_type"] != self.root_type:
                throw(f"{self.parent_account} is a {parent['root_type']} account; this one is {self.root_type}. A group can only hold accounts of its own type.")
            seen, cursor = {self.name}, parent
            while cursor and cursor.get("parent_account"):                    # walk up: a loop would make the group its own ancestor
                if cursor["parent_account"] in seen:
                    throw("That parent would put this account under itself.")
                seen.add(cursor["parent_account"])
                cursor = row("Account", cursor["parent_account"], "name", "parent_account")
        if not self.is_new():
            accounts = get_table("Account")
            with db.transaction() as c:
                children = c.execute(select(func.count()).select_from(accounts).where(accounts.c.parent_account == self.name)).scalar()
            if children and not self.is_group:
                throw(f"{self.name} has {children} account(s) listed under it, so it has to stay a group account.")
            if self.is_group:
                ledger = get_table("Account Ledger Record")
                with db.transaction() as c:
                    used = c.execute(select(func.count()).select_from(ledger).where(ledger.c.account == self.name)).scalar()
                if used:
                    throw(f"{self.name} already has {used} posting(s), so it cannot become a group account. Create a new group and list it under that instead.")

    def before_delete(self):
        from sqlalchemy import select
        from velora import db
        from velora.db.tables import get_table
        table = get_table("Account Statement Mapping")
        with db.transaction() as conn:
            if conn.execute(select(table.c.name).where(table.c.account == self.name).limit(1)).first():
                throw("This account is referenced by a financial statement mapping; disable it instead")
