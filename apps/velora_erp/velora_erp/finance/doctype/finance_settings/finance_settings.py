from velora import Document, get_list, throw


class FinanceSettings(Document):
    def validate(self):
        self.settings_name = (self.settings_name or "Primary Finance Settings").strip()
        existing = get_list("Finance Settings", fields=["name"], limit=2, ignore_permissions=True)
        if any(row["name"] != self.name for row in existing):
            throw("Only one Finance Settings record is permitted in this company database. Use its tabs to manage all financial configuration.")
        self.country_code = (self.country_code or "").strip().upper()
        self.base_currency = (self.base_currency or "").strip().upper()
        if len(self.country_code) != 2:
            throw("Country Code must contain exactly two letters, for example GB.")
        if len(self.base_currency) != 3:
            throw("Base Currency must be a three-letter currency code, for example USD.")
        if self.decimal_places is None or not 0 <= int(self.decimal_places) <= 6:
            throw("Currency Decimal Places must be between 0 and 6.")
        if self.backdated_posting_days is not None and int(self.backdated_posting_days) < 0:
            throw("Maximum Backdating Days cannot be negative.")
        cap = self.maximum_loan_deduction_percent_of_net_pay if getattr(self, "maximum_loan_deduction_percent_of_net_pay", None) not in (None, "") else 30
        if not 0 <= float(cap) <= 100:
            throw("Maximum Combined Loan Deduction must be between 0 and 100 percent.")
        floor = self.minimum_net_pay_after_loan_deductions if getattr(self, "minimum_net_pay_after_loan_deductions", None) not in (None, "") else 0
        if float(floor) < 0:
            throw("Minimum Net Pay After Loan Deductions cannot be negative.")
        if getattr(self, "loan_recovery_allocation_method", None) not in (None, "", "Oldest Due First", "Highest Interest First", "Lowest Balance First", "Pro Rata"):
            throw("Select a valid default loan recovery allocation method.")

        self._validate_exchange_accounts()
        self._validate_cost_distribution()
        self._validate_investments()
        from velora_erp.finance.approval_policy import sync_rows
        sync_rows(self)
        from velora_erp.finance import approval_authority
        try:
            approval_authority.sync_rows(self)
        except approval_authority.ApprovalAuthorityError as error:
            throw(str(error))

    def _validate_exchange_accounts(self):
        from velora import get_doc
        for field, root in (("realised_exchange_gain_account", "Income"), ("unrealised_exchange_gain_account", "Income"), ("realised_exchange_loss_account", "Expense"), ("unrealised_exchange_loss_account", "Expense")):
            name = getattr(self, field, None)
            if name:
                account = get_doc("Account", name)
                if account.disabled or account.is_group or account.root_type != root:
                    throw(f"{field.replace('_', ' ').capitalize()} must be an active {root} ledger account.")

    def _validate_investments(self):
        for field, label in (("investment_default_wht_rate", "Default withholding tax rate"), ("investment_max_counterparty_percent", "Counterparty limit"),
                             ("investment_max_asset_group_percent", "Asset group limit")):
            value = getattr(self, field, None)
            if value not in (None, "") and not 0 <= float(value) <= 100:
                throw(f"{label} must be between 0 and 100 percent.")
        days = getattr(self, "investment_maturity_alert_days", None)
        if days not in (None, "") and int(days) < 0:
            throw("Maturity warning days cannot be negative.")

    def _validate_cost_distribution(self):
        rules = {}
        for line in self.cost_distribution_lines or []:
            name = (line.rule_name or "").strip()
            if not name:
                throw("Every Cost Distribution row needs a rule name.")
            line.rule_name = name
            pct = float(line.percentage or 0)
            if pct <= 0 or pct > 100:
                throw(f"Cost Distribution rule {name}: each percentage must be above 0 and at most 100.")
            if line.cost_centre in {r[0] for r in rules.setdefault(name, [])}:
                throw(f"Cost Distribution rule {name}: cost centre {line.cost_centre} is listed twice.")
            rules[name].append((line.cost_centre, pct))
        for name, rows in rules.items():
            if abs(sum(p for _, p in rows) - 100) > 0.005:
                throw(f"Cost Distribution rule {name} totals {sum(p for _, p in rows):g}%; it must total exactly 100%.")

    def on_update(self):
        """Keep one selectable Cost Distribution Rule record per rule named in the table, and switch on the workflow of every document that now requires approval."""
        from velora import new_doc
        from velora_erp.finance.approval_policy import apply
        apply(self)
        wanted = {(l.rule_name or "").strip() for l in self.cost_distribution_lines or [] if (l.rule_name or "").strip()}
        have = {r["name"] for r in get_list("Cost Distribution Rule", fields=["name"], limit=1000, ignore_permissions=True)}
        for name in sorted(wanted - have):
            new_doc("Cost Distribution Rule", rule_name=name).insert(ignore_permissions=True)
